"""Durable folder-sync queue.

Replaces the in-memory task table of v0.0.1. The queue lives in ``sync_job``
so that unfinished work, retry backoff and cancellation all survive a restart,
which is what makes a whole-mailbox sync explainable and recoverable.

Concurrency follows PLAN.md: within one account only a single job runs at a
time, while different accounts may proceed in parallel. v0.1 ships with one
worker, which also guarantees cross-folder serialisation. Each worker keeps
one IMAP connection alive across the jobs of a batch, so a whole-mailbox run
pays for LOGIN once instead of once per folder.

Note that raising ``max_workers`` gives every worker its own parked
connection, so the one-LOGIN-per-batch property is exact at the default of a
single worker and approximate above it. Jobs stay serialised per account
either way.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.sync import SyncJob
from hymail_api.domain.enums import (
    AccountStatus,
    SyncBatchState,
    SyncJobKind,
    SyncJobState,
    SyncPriority,
)
from hymail_api.imap.client import ImapClient
from hymail_api.imap.errors import (
    ImapAuthenticationError,
    ImapConnectionError,
    ImapError,
    ImapFolderNotFoundError,
)
from hymail_api.sync.backoff import calculate_backoff_delay
from hymail_api.sync.engine import SyncEngine

logger = logging.getLogger(__name__)

_ACTIVE_STATES = (SyncJobState.QUEUED.value, SyncJobState.RUNNING.value)


class AccountPausedError(RuntimeError):
    """Raised when the account needs re-authorising before it can sync."""


@dataclass(slots=True)
class ClaimedJob:
    job_id: UUID
    account_id: UUID
    folder_id: UUID
    folder_name: str
    batch_id: UUID
    attempts: int
    kind: str = SyncJobKind.SYNC.value


@dataclass(slots=True)
class BatchSummary:
    batch_id: UUID
    total: int
    queued: int
    running: int
    success: int
    failed: int
    cancelled: int
    state: SyncBatchState
    current_folder: str | None
    last_error: str | None


@dataclass(slots=True)
class _Connection:
    """One IMAP session shared by the jobs of a batch."""

    client: ImapClient | None = None
    batch_id: UUID | None = None

    async def close(self) -> None:
        await _close(self.client)
        self.client = None


@dataclass(slots=True)
class _JobTask:
    task: asyncio.Task[None]
    cancelled_by_user: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


class SyncScheduler:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client_factory: Callable[[Account], ImapClient],
        batch_size: int = 50,
        max_attempts: int = 3,
        lease_seconds: float = 120.0,
        backoff_base_seconds: float = 1.0,
        max_backoff_seconds: float = 300.0,
        poll_interval: float = 0.5,
        max_workers: int = 1,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")

        self._session_factory = session_factory
        self._client_factory = client_factory
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds
        self._backoff_base_seconds = backoff_base_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._poll_interval = poll_interval
        self._max_workers = max_workers

        self._workers: list[asyncio.Task[None]] = []
        self._running: dict[UUID, _JobTask] = {}
        self._stopping = False
        self._wakeup = asyncio.Event()
        self._start_lock = asyncio.Lock()
        # Serialises claim transactions so two workers cannot both observe an
        # account as idle and start syncing it.
        self._claim_lock = asyncio.Lock()

    # ------------------------------------------------------------------ life

    async def ensure_started(self) -> None:
        async with self._start_lock:
            if self._workers:
                return
            await self.recover_stale_jobs()
            self._stopping = False
            self._workers = [
                asyncio.create_task(self._worker())
                for _ in range(self._max_workers)
            ]

    async def stop(self) -> None:
        """Ask workers to finish their current step and exit.

        Cancelling outright can land mid-query and leave an aiosqlite thread
        delivering a result to a closed loop, so workers are woken and given a
        moment to leave their loop on their own first.
        """
        workers, self._workers = self._workers, []
        if not workers:
            return
        self._stopping = True
        self._wakeup.set()
        for worker in workers:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(worker, timeout=5.0)
            if not worker.done():
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
        self._stopping = False

    async def recover_stale_jobs(self) -> int:
        """Re-queue jobs whose worker died while holding a lease.

        This is the crash-recovery half of the design: the queue is only as
        durable as its ability to notice abandoned work.
        """
        now = _now()
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(SyncJob)
                .where(
                    SyncJob.state == SyncJobState.RUNNING.value,
                    SyncJob.lease_expires_at.is_not(None),
                    SyncJob.lease_expires_at < now,
                )
                .values(
                    state=SyncJobState.QUEUED.value,
                    lease_expires_at=None,
                    not_before=None,
                    last_error="requeued after lease expiry",
                )
            )
        recovered = result.rowcount or 0
        if recovered:
            logger.warning("requeued %s abandoned sync job(s)", recovered)
        return recovered

    # --------------------------------------------------------------- enqueue

    async def enqueue_folder(
        self,
        account_id: UUID,
        folder_id: UUID,
        *,
        priority: SyncPriority = SyncPriority.USER,
        batch_id: UUID | None = None,
        kind: SyncJobKind = SyncJobKind.SYNC,
    ) -> SyncJob:
        """Queue one folder, or hand back the job already in flight for it."""
        jobs = await self.enqueue_folders(
            account_id,
            [folder_id],
            priority=priority,
            batch_id=batch_id,
            kind=kind,
        )
        if jobs:
            return jobs[0]

        existing = await self._find_active_job(account_id, folder_id)
        if existing is None:
            raise RuntimeError("folder could not be queued")
        return existing

    async def enqueue_folders(
        self,
        account_id: UUID,
        folder_ids: Sequence[UUID],
        *,
        priority: SyncPriority = SyncPriority.USER,
        batch_id: UUID | None = None,
        kind: SyncJobKind = SyncJobKind.SYNC,
    ) -> list[SyncJob]:
        """Queue folders, skipping any that already have work in flight.

        A folder that is already queued or running is skipped regardless of
        kind: syncing and reconciling the same mailbox at once would only
        duplicate work.
        """
        if not folder_ids:
            return []

        await self._ensure_account_active(account_id)
        batch = batch_id or uuid4()
        now = _now()

        async with self._session_factory() as session, session.begin():
            active = set(
                await session.scalars(
                    select(SyncJob.folder_id).where(
                        SyncJob.account_id == account_id,
                        SyncJob.state.in_(_ACTIVE_STATES),
                    )
                )
            )
            created: list[SyncJob] = []
            for folder_id in folder_ids:
                if folder_id in active:
                    continue
                job = SyncJob(
                    account_id=account_id,
                    folder_id=folder_id,
                    batch_id=batch,
                    kind=kind.value,
                    state=SyncJobState.QUEUED.value,
                    priority=int(priority),
                    not_before=now,
                )
                session.add(job)
                created.append(job)
                active.add(folder_id)
            await session.flush()
            for job in created:
                session.expunge(job)

        await self.ensure_started()
        self._wakeup.set()
        return created

    async def _find_active_job(
        self,
        account_id: UUID,
        folder_id: UUID,
    ) -> SyncJob | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(SyncJob).where(
                    SyncJob.account_id == account_id,
                    SyncJob.folder_id == folder_id,
                    SyncJob.state.in_(_ACTIVE_STATES),
                )
            )

    async def _ensure_account_active(self, account_id: UUID) -> None:
        async with self._session_factory() as session:
            status = await session.scalar(
                select(Account.status).where(Account.id == account_id)
            )
        if status == AccountStatus.AUTH_EXPIRED.value:
            raise AccountPausedError(
                "account authentication expired; re-authorise before syncing"
            )

    # ---------------------------------------------------------------- cancel

    async def cancel_batch(self, batch_id: UUID) -> int:
        return await self._cancel(where=(SyncJob.batch_id == batch_id))

    async def cancel_folder(self, account_id: UUID, folder_id: UUID) -> int:
        return await self._cancel(
            where=(
                (SyncJob.account_id == account_id)
                & (SyncJob.folder_id == folder_id)
            )
        )

    async def _cancel(self, *, where) -> int:
        """Cancel queued jobs and stop any running ones.

        A running job is a separate task so that cancelling it does not tear
        down the worker; the worker notices the user cancellation and records
        the job as cancelled instead of re-queueing it.
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(SyncJob.id, SyncJob.state).where(
                        where,
                        SyncJob.state.in_(_ACTIVE_STATES),
                    )
                )
            ).all()

        stopped = 0
        for job_id, state in rows:
            if state != SyncJobState.RUNNING.value:
                continue
            running = self._running.get(job_id)
            if running is not None and not running.task.done():
                running.cancelled_by_user = True
                running.task.cancel()
                stopped += 1

        now = _now()
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(SyncJob)
                .where(where, SyncJob.state == SyncJobState.QUEUED.value)
                .values(
                    state=SyncJobState.CANCELLED.value,
                    finished_at=now,
                    last_error="cancelled by user",
                )
            )
        return stopped + (result.rowcount or 0)

    # ------------------------------------------------------------ inspection

    async def batch_summary(self, batch_id: UUID) -> BatchSummary | None:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(SyncJob.state, func.count())
                    .where(SyncJob.batch_id == batch_id)
                    .group_by(SyncJob.state)
                )
            ).all()
            if not rows:
                return None

            counts = {state: int(count) for state, count in rows}
            current = await session.scalar(
                select(Folder.name)
                .join(SyncJob, SyncJob.folder_id == Folder.id)
                .where(
                    SyncJob.batch_id == batch_id,
                    SyncJob.state == SyncJobState.RUNNING.value,
                )
                .limit(1)
            )
            last_error = await session.scalar(
                select(SyncJob.last_error)
                .where(
                    SyncJob.batch_id == batch_id,
                    SyncJob.last_error.is_not(None),
                )
                .order_by(SyncJob.finished_at.desc())
                .limit(1)
            )

        return _summarise(
            batch_id,
            counts,
            current_folder=current,
            last_error=last_error,
        )

    async def list_jobs(
        self,
        account_id: UUID,
        *,
        limit: int = 50,
    ) -> list[tuple[SyncJob, str]]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(SyncJob, Folder.name)
                    .join(Folder, Folder.id == SyncJob.folder_id)
                    .where(SyncJob.account_id == account_id)
                    .order_by(SyncJob.created_at.desc(), SyncJob.id)
                    .limit(limit)
                )
            ).all()
        return [(job, name) for job, name in rows]

    async def drain(self, deadline_seconds: float = 10.0) -> None:
        """Block until nothing is queued or running. Intended for tests."""
        deadline = asyncio.get_running_loop().time() + deadline_seconds
        while True:
            async with self._session_factory() as session:
                pending = await session.scalar(
                    select(func.count())
                    .select_from(SyncJob)
                    .where(SyncJob.state.in_(_ACTIVE_STATES))
                )
            if not pending:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("sync queue did not drain in time")
            await asyncio.sleep(0.02)

    # ---------------------------------------------------------------- worker

    async def _worker(self) -> None:
        connection = _Connection()
        try:
            while not self._stopping:
                claimed = await self._claim_next()
                if claimed is None:
                    await connection.close()
                    connection.batch_id = None
                    await self._wait_for_work()
                    continue

                # One connection per batch: LOGIN is the expensive, rate
                # limited operation, so a whole-mailbox run pays it once.
                if claimed.batch_id != connection.batch_id:
                    await connection.close()
                    connection.batch_id = claimed.batch_id

                running = _JobTask(
                    task=asyncio.create_task(
                        self._run_job(claimed, connection)
                    )
                )
                self._running[claimed.job_id] = running
                try:
                    await running.task
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    worker_cancelled = bool(current and current.cancelling())
                    if not worker_cancelled and running.cancelled_by_user:
                        await self._finish(
                            claimed,
                            SyncJobState.CANCELLED,
                            "cancelled by user",
                        )
                        continue
                    await connection.close()
                    await self._requeue(claimed, "scheduler stopped", 0.0)
                    raise
                finally:
                    self._running.pop(claimed.job_id, None)
        finally:
            await connection.close()

    async def _run_job(self, claimed: ClaimedJob, connection: _Connection) -> None:
        try:
            account = await self._load_account(claimed.account_id)
            if account is None:
                await self._finish(
                    claimed,
                    SyncJobState.FAILED,
                    "account not found",
                )
                return
            if connection.client is None:
                connection.client = self._client_factory(account)
                await connection.client.connect()
            await self._execute(claimed, connection.client)
        except ImapConnectionError as exc:
            await connection.close()
            await self._fail_or_retry(claimed, exc)
        except ImapAuthenticationError as exc:
            await connection.close()
            await self._auth_failed(claimed, exc)
        except ImapFolderNotFoundError as exc:
            # Permanent: the mailbox exists locally but not on the server.
            await self._finish(claimed, SyncJobState.FAILED, str(exc))
        except ImapError as exc:
            await self._fail_or_retry(claimed, exc)
        except asyncio.CancelledError:
            # The socket is mid-command, so it cannot be reused.
            await connection.close()
            raise
        except Exception as exc:  # noqa: BLE001 - keep the queue alive
            logger.exception("sync job %s crashed", claimed.job_id)
            await self._finish(claimed, SyncJobState.FAILED, str(exc))

    async def _wait_for_work(self) -> None:
        try:
            await asyncio.wait_for(
                self._wakeup.wait(),
                timeout=self._poll_interval,
            )
        except TimeoutError:
            pass
        finally:
            self._wakeup.clear()

    async def _load_account(self, account_id: UUID) -> Account | None:
        async with self._session_factory() as session:
            return await session.get(Account, account_id)

    async def _execute(self, claimed: ClaimedJob, client: ImapClient) -> None:
        engine = SyncEngine(
            session_factory=self._session_factory,
            imap_client_factory=lambda: client,
            batch_size=self._batch_size,
        )
        if claimed.kind == SyncJobKind.RECONCILE.value:
            await engine.reconcile_folder(
                claimed.account_id,
                claimed.folder_name,
                client=client,
            )
        else:
            await engine.sync_folder(
                claimed.account_id,
                claimed.folder_name,
                client=client,
            )
        await self._finish(claimed, SyncJobState.SUCCESS, None)

    async def _claim_next(self) -> ClaimedJob | None:
        now = _now()
        async with (
            self._claim_lock,
            self._session_factory() as session,
            session.begin(),
        ):
            busy = select(SyncJob.account_id).where(
                SyncJob.state == SyncJobState.RUNNING.value
            )
            candidate = await session.scalar(
                select(SyncJob)
                .where(
                    SyncJob.state == SyncJobState.QUEUED.value,
                    SyncJob.account_id.not_in(busy),
                    (SyncJob.not_before.is_(None)) | (SyncJob.not_before <= now),
                )
                .order_by(
                    SyncJob.priority,
                    SyncJob.created_at,
                    SyncJob.id,
                )
                .limit(1)
            )
            if candidate is None:
                return None

            claimed = await session.execute(
                update(SyncJob)
                .where(
                    SyncJob.id == candidate.id,
                    SyncJob.state == SyncJobState.QUEUED.value,
                )
                .values(
                    state=SyncJobState.RUNNING.value,
                    attempts=SyncJob.attempts + 1,
                    started_at=now,
                    lease_expires_at=now
                    + timedelta(seconds=self._lease_seconds),
                    last_error=None,
                )
            )
            if claimed.rowcount != 1:
                return None

            folder_name = await session.scalar(
                select(Folder.name).where(Folder.id == candidate.folder_id)
            )
            if folder_name is None:
                return None

            return ClaimedJob(
                job_id=candidate.id,
                account_id=candidate.account_id,
                folder_id=candidate.folder_id,
                folder_name=folder_name,
                batch_id=candidate.batch_id,
                attempts=candidate.attempts + 1,
                kind=candidate.kind,
            )

    async def _finish(
        self,
        claimed: ClaimedJob,
        state: SyncJobState,
        error: str | None,
    ) -> None:
        now = _now()
        async with self._session_factory() as session, session.begin():
            job = await session.get(SyncJob, claimed.job_id)
            if job is None:
                return
            job.state = state.value
            job.last_error = error
            job.lease_expires_at = None
            job.finished_at = now
            job.not_before = None

    async def _requeue(
        self,
        claimed: ClaimedJob,
        error: str,
        delay_seconds: float,
    ) -> None:
        now = _now()
        async with self._session_factory() as session, session.begin():
            job = await session.get(SyncJob, claimed.job_id)
            if job is None:
                return
            job.state = SyncJobState.QUEUED.value
            job.last_error = error
            job.lease_expires_at = None
            job.not_before = now + timedelta(seconds=delay_seconds)

    async def _fail_or_retry(self, claimed: ClaimedJob, exc: ImapError) -> None:
        if claimed.attempts >= self._max_attempts:
            await self._finish(claimed, SyncJobState.FAILED, str(exc))
            return
        delay = calculate_backoff_delay(
            claimed.attempts,
            base_seconds=self._backoff_base_seconds,
            max_seconds=self._max_backoff_seconds,
        )
        await self._requeue(claimed, str(exc), delay)

    async def _auth_failed(
        self,
        claimed: ClaimedJob,
        exc: ImapAuthenticationError,
    ) -> None:
        """Pause the account and drop its remaining queue.

        Every further job would fail the same way, so leaving them queued
        would only be noise in the UI.
        """
        now = _now()
        async with self._session_factory() as session, session.begin():
            account = await session.get(Account, claimed.account_id)
            if account is not None:
                account.status = AccountStatus.AUTH_EXPIRED.value

            job = await session.get(SyncJob, claimed.job_id)
            if job is not None:
                job.state = SyncJobState.FAILED.value
                job.last_error = str(exc)
                job.lease_expires_at = None
                job.finished_at = now

            await session.execute(
                update(SyncJob)
                .where(
                    SyncJob.account_id == claimed.account_id,
                    SyncJob.state == SyncJobState.QUEUED.value,
                )
                .values(
                    state=SyncJobState.CANCELLED.value,
                    finished_at=now,
                    last_error="account authentication expired",
                )
            )


async def _close(client: ImapClient | None) -> None:
    if client is None:
        return
    try:
        await client.close()
    except Exception:  # noqa: BLE001 - closing must never break the queue
        logger.debug("failed to close IMAP connection", exc_info=True)


def _summarise(
    batch_id: UUID,
    counts: dict[str, int],
    *,
    current_folder: str | None,
    last_error: str | None,
) -> BatchSummary:
    total = sum(counts.values())
    queued = counts.get(SyncJobState.QUEUED.value, 0)
    running = counts.get(SyncJobState.RUNNING.value, 0)
    success = counts.get(SyncJobState.SUCCESS.value, 0)
    failed = counts.get(SyncJobState.FAILED.value, 0)
    cancelled = counts.get(SyncJobState.CANCELLED.value, 0)

    if total == 0:
        state = SyncBatchState.EMPTY
    elif running:
        state = SyncBatchState.RUNNING
    elif queued:
        state = SyncBatchState.QUEUED
    elif failed == total:
        state = SyncBatchState.FAILED
    elif cancelled == total:
        state = SyncBatchState.CANCELLED
    elif success == total:
        state = SyncBatchState.COMPLETED
    else:
        state = SyncBatchState.PARTIAL

    return BatchSummary(
        batch_id=batch_id,
        total=total,
        queued=queued,
        running=running,
        success=success,
        failed=failed,
        cancelled=cancelled,
        state=state,
        current_folder=current_folder,
        last_error=last_error,
    )

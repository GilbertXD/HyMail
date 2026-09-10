"""Durable outbox for local flag changes.

Optimistic UI is only honest if the intent outlives the process: the row is
written before the interface claims anything happened, and a worker drains it
with leases and backoff.

Two rules keep it from lying:

* A newer toggle for the same message and flag supersedes the queued one, so
  flipping read/unread twice sends one write rather than two contradictory
  ones.
* The worker will not touch an account that is already syncing, so the app
  never holds two IMAP connections to the same mailbox.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.db.models.outbox import OutboxAction
from hymail_api.db.models.sync import SyncJob
from hymail_api.domain.enums import (
    AccountStatus,
    OutboxActionState,
    OutboxActionType,
    SyncJobState,
)
from hymail_api.imap.client import ImapClient
from hymail_api.imap.errors import (
    ImapAuthenticationError,
    ImapConnectionError,
    ImapError,
    ImapFolderNotFoundError,
)
from hymail_api.sync.backoff import calculate_backoff_delay
from hymail_api.sync.flags import (
    flags_to_state,
    read_toggle_flags,
    star_toggle_flags,
)

logger = logging.getLogger(__name__)

_ACTIVE_STATES = (
    OutboxActionState.PENDING.value,
    OutboxActionState.INFLIGHT.value,
)


@dataclass(slots=True)
class ClaimedAction:
    action_id: UUID
    account_id: UUID
    message_id: UUID
    folder_id: UUID
    folder_name: str
    uid: int
    type: str
    value: bool
    attempts: int


def _now() -> datetime:
    return datetime.now(UTC)


class OutboxDispatcher:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client_factory: Callable[[Account], ImapClient],
        max_attempts: int = 5,
        lease_seconds: float = 60.0,
        backoff_base_seconds: float = 1.0,
        max_backoff_seconds: float = 300.0,
        poll_interval: float = 0.5,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self._session_factory = session_factory
        self._client_factory = client_factory
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds
        self._backoff_base_seconds = backoff_base_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._poll_interval = poll_interval

        self._worker: asyncio.Task[None] | None = None
        self._stopping = False
        self._wakeup = asyncio.Event()
        self._start_lock = asyncio.Lock()
        self._claim_lock = asyncio.Lock()

    # ------------------------------------------------------------------ life

    async def ensure_started(self) -> None:
        async with self._start_lock:
            if self._worker is not None and not self._worker.done():
                return
            await self.recover_stale_actions()
            self._stopping = False
            self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Ask the worker to finish its current step and exit.

        Cancelling outright can land mid-query and leave an aiosqlite thread
        delivering a result to a closed loop, so the worker is woken and given
        a moment to leave the loop on its own first.
        """
        worker, self._worker = self._worker, None
        if worker is None:
            return
        self._stopping = True
        self._wakeup.set()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(worker, timeout=5.0)
        if not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._stopping = False

    async def recover_stale_actions(self) -> int:
        """Re-queue actions whose worker died while holding a lease."""
        now = _now()
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(OutboxAction)
                .where(
                    OutboxAction.state == OutboxActionState.INFLIGHT.value,
                    OutboxAction.lease_expires_at.is_not(None),
                    OutboxAction.lease_expires_at < now,
                )
                .values(
                    state=OutboxActionState.PENDING.value,
                    lease_expires_at=None,
                    next_retry_at=None,
                    last_error="requeued after lease expiry",
                )
            )
        recovered = result.rowcount or 0
        if recovered:
            logger.warning("requeued %s abandoned outbox action(s)", recovered)
        return recovered

    # --------------------------------------------------------------- enqueue

    async def enqueue_flag_change(
        self,
        *,
        account_id: UUID,
        message_id: UUID,
        folder_id: UUID,
        uid: int,
        action_type: OutboxActionType,
        value: bool,
        session: AsyncSession | None = None,
    ) -> OutboxAction | None:
        """Queue a flag write, coalescing with any queued change of the same kind.

        Returns ``None`` when the server is already going to be told exactly
        this, which is what makes a repeated toggle a no-op. Pass ``session``
        to enrol the write in a caller's transaction, so the optimistic local
        update and the queued intent commit together.
        """
        if session is not None:
            return await self._enqueue(
                session,
                account_id=account_id,
                message_id=message_id,
                folder_id=folder_id,
                uid=uid,
                action_type=action_type,
                value=value,
            )

        async with self._session_factory() as own_session, own_session.begin():
            action = await self._enqueue(
                own_session,
                account_id=account_id,
                message_id=message_id,
                folder_id=folder_id,
                uid=uid,
                action_type=action_type,
                value=value,
            )

        if action is not None:
            await self.ensure_started()
            self._wakeup.set()
        return action

    async def _enqueue(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        message_id: UUID,
        folder_id: UUID,
        uid: int,
        action_type: OutboxActionType,
        value: bool,
    ) -> OutboxAction | None:
        now = _now()
        existing = await session.scalar(
            select(OutboxAction).where(
                OutboxAction.message_id == message_id,
                OutboxAction.type == action_type.value,
                OutboxAction.state == OutboxActionState.PENDING.value,
            )
        )
        if existing is not None:
            if existing.payload_json.get("value") == value:
                return None
            existing.payload_json = {"value": value}
            existing.uid = uid
            existing.folder_id = folder_id
            existing.attempts = 0
            existing.last_error = None
            existing.next_retry_at = now
            await session.flush()
            return existing

        action = OutboxAction(
            account_id=account_id,
            message_id=message_id,
            folder_id=folder_id,
            uid=uid,
            type=action_type.value,
            payload_json={"value": value},
            state=OutboxActionState.PENDING.value,
            next_retry_at=now,
        )
        session.add(action)
        await session.flush()
        return action

    async def notify(self) -> None:
        """Wake the worker after a caller committed its own enqueue."""
        await self.ensure_started()
        self._wakeup.set()

    # ------------------------------------------------------------- operator

    async def retry(self, action_id: UUID, *, account_id: UUID | None = None) -> bool:
        async with self._session_factory() as session, session.begin():
            action = await session.get(OutboxAction, action_id)
            if action is None or (
                account_id is not None and action.account_id != account_id
            ):
                return False
            if action.state not in {
                OutboxActionState.FAILED.value,
                OutboxActionState.ABANDONED.value,
            }:
                return False
            action.state = OutboxActionState.PENDING.value
            action.attempts = 0
            action.last_error = None
            action.next_retry_at = _now()
            action.finished_at = None

        await self.ensure_started()
        self._wakeup.set()
        return True

    async def discard(
        self,
        action_id: UUID,
        *,
        account_id: UUID | None = None,
    ) -> bool:
        """Drop a queued change and put the local row back to the server value.

        Rolling back uses ``flags_json``, which always holds the flags as the
        server last reported them.
        """
        now = _now()
        async with self._session_factory() as session, session.begin():
            action = await session.get(OutboxAction, action_id)
            if action is None or (
                account_id is not None and action.account_id != account_id
            ):
                return False
            if action.state not in _ACTIVE_STATES + (
                OutboxActionState.FAILED.value,
            ):
                return False

            action.state = OutboxActionState.ABANDONED.value
            action.lease_expires_at = None
            action.finished_at = now
            action.last_error = "discarded by user"

            message = await session.get(Message, action.message_id)
            if message is not None:
                is_read, is_starred = flags_to_state(message.flags_json or [])
                if action.type == OutboxActionType.MARK_READ.value:
                    message.is_read = is_read
                elif action.type == OutboxActionType.STAR.value:
                    message.is_starred = is_starred

        return True

    async def list_actions(
        self,
        account_id: UUID,
        *,
        limit: int = 50,
        active_only: bool = False,
    ) -> list[tuple[OutboxAction, str | None, str]]:
        async with self._session_factory() as session:
            statement = (
                select(OutboxAction, Message.subject, Folder.name)
                .join(Message, Message.id == OutboxAction.message_id)
                .join(Folder, Folder.id == OutboxAction.folder_id)
                .where(OutboxAction.account_id == account_id)
                .order_by(OutboxAction.created_at.desc())
                .limit(limit)
            )
            if active_only:
                statement = statement.where(
                    OutboxAction.state.in_(_ACTIVE_STATES)
                )
            rows = (await session.execute(statement)).all()
        return [(action, subject, folder) for action, subject, folder in rows]

    async def pending_message_ids(
        self,
        account_id: UUID,
    ) -> dict[UUID, str]:
        """message_id -> worst state, for flagging rows that have not synced."""
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(OutboxAction.message_id, OutboxAction.state).where(
                        OutboxAction.account_id == account_id,
                        OutboxAction.state.in_(
                            _ACTIVE_STATES
                            + (OutboxActionState.FAILED.value,)
                        ),
                    )
                )
            ).all()

        worst: dict[UUID, str] = {}
        for message_id, state in rows:
            current = worst.get(message_id)
            if current == OutboxActionState.FAILED.value:
                continue
            worst[message_id] = state
        return worst

    async def drain(self, deadline_seconds: float = 10.0) -> None:
        """Block until nothing is pending or in flight. Intended for tests."""
        deadline = asyncio.get_running_loop().time() + deadline_seconds
        while True:
            async with self._session_factory() as session:
                pending = await session.scalar(
                    select(func.count())
                    .select_from(OutboxAction)
                    .where(OutboxAction.state.in_(_ACTIVE_STATES))
                )
            if not pending:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("outbox did not drain in time")
            await asyncio.sleep(0.02)

    # ---------------------------------------------------------------- worker

    async def _run(self) -> None:
        client: ImapClient | None = None
        active_account: UUID | None = None

        try:
            while not self._stopping:
                claimed = await self._claim_next()
                if claimed is None:
                    await _close(client)
                    client, active_account = None, None
                    await self._wait_for_work()
                    continue

                if claimed.account_id != active_account:
                    await _close(client)
                    client, active_account = None, claimed.account_id

                try:
                    account = await self._load_account(claimed.account_id)
                    if account is None:
                        await self._finish(
                            claimed,
                            OutboxActionState.FAILED,
                            "account not found",
                        )
                        continue
                    if client is None:
                        client = self._client_factory(account)
                        await client.connect()
                    await self._execute(claimed, client)
                except ImapConnectionError as exc:
                    await _close(client)
                    client = None
                    await self._fail_or_retry(claimed, exc)
                except ImapAuthenticationError as exc:
                    await _close(client)
                    client = None
                    await self._auth_failed(claimed, exc)
                except ImapFolderNotFoundError as exc:
                    await self._finish(
                        claimed,
                        OutboxActionState.FAILED,
                        str(exc),
                    )
                except ImapError as exc:
                    await self._fail_or_retry(claimed, exc)
                except asyncio.CancelledError:
                    await _close(client)
                    client = None
                    await self._requeue(claimed, "outbox stopped", 0.0)
                    raise
                except Exception as exc:  # noqa: BLE001 - keep the loop alive
                    logger.exception("outbox action %s crashed", claimed.action_id)
                    await self._finish(
                        claimed,
                        OutboxActionState.FAILED,
                        str(exc),
                    )
        finally:
            await _close(client)

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

    async def _execute(self, claimed: ClaimedAction, client: ImapClient) -> None:
        if claimed.type == OutboxActionType.MARK_READ.value:
            flags, add = read_toggle_flags(claimed.value)
        else:
            flags, add = star_toggle_flags(claimed.value)

        await client.store_flags(
            claimed.folder_name,
            claimed.uid,
            flags,
            add=add,
        )
        await self._finish(claimed, OutboxActionState.SUCCESS, None)

    async def _claim_next(self) -> ClaimedAction | None:
        now = _now()
        async with (
            self._claim_lock,
            self._session_factory() as session,
            session.begin(),
        ):
            # An account that is syncing, or already has a write in flight, is
            # busy: the app must not hold two IMAP connections to one mailbox.
            syncing = select(SyncJob.account_id).where(
                SyncJob.state == SyncJobState.RUNNING.value
            )
            writing = select(OutboxAction.account_id).where(
                OutboxAction.state == OutboxActionState.INFLIGHT.value
            )
            candidate = await session.scalar(
                select(OutboxAction)
                .where(
                    OutboxAction.state == OutboxActionState.PENDING.value,
                    OutboxAction.account_id.not_in(syncing),
                    OutboxAction.account_id.not_in(writing),
                    (OutboxAction.next_retry_at.is_(None))
                    | (OutboxAction.next_retry_at <= now),
                )
                .order_by(OutboxAction.created_at, OutboxAction.id)
                .limit(1)
            )
            if candidate is None:
                return None

            claimed = await session.execute(
                update(OutboxAction)
                .where(
                    OutboxAction.id == candidate.id,
                    OutboxAction.state == OutboxActionState.PENDING.value,
                )
                .values(
                    state=OutboxActionState.INFLIGHT.value,
                    attempts=OutboxAction.attempts + 1,
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

            return ClaimedAction(
                action_id=candidate.id,
                account_id=candidate.account_id,
                message_id=candidate.message_id,
                folder_id=candidate.folder_id,
                folder_name=folder_name,
                uid=candidate.uid,
                type=candidate.type,
                value=bool(candidate.payload_json.get("value", True)),
                attempts=candidate.attempts + 1,
            )

    async def _finish(
        self,
        claimed: ClaimedAction,
        state: OutboxActionState,
        error: str | None,
    ) -> None:
        now = _now()
        async with self._session_factory() as session, session.begin():
            action = await session.get(OutboxAction, claimed.action_id)
            if action is None:
                return
            action.state = state.value
            action.last_error = error
            action.lease_expires_at = None
            action.finished_at = now
            action.next_retry_at = None

    async def _requeue(
        self,
        claimed: ClaimedAction,
        error: str,
        delay_seconds: float,
    ) -> None:
        now = _now()
        async with self._session_factory() as session, session.begin():
            action = await session.get(OutboxAction, claimed.action_id)
            if action is None:
                return
            action.state = OutboxActionState.PENDING.value
            action.last_error = error
            action.lease_expires_at = None
            action.next_retry_at = now + timedelta(seconds=delay_seconds)

    async def _fail_or_retry(self, claimed: ClaimedAction, exc: ImapError) -> None:
        if claimed.attempts >= self._max_attempts:
            await self._finish(claimed, OutboxActionState.FAILED, str(exc))
            return
        delay = calculate_backoff_delay(
            claimed.attempts,
            base_seconds=self._backoff_base_seconds,
            max_seconds=self._max_backoff_seconds,
        )
        await self._requeue(claimed, str(exc), delay)

    async def _auth_failed(
        self,
        claimed: ClaimedAction,
        exc: ImapAuthenticationError,
    ) -> None:
        now = _now()
        async with self._session_factory() as session, session.begin():
            account = await session.get(Account, claimed.account_id)
            if account is not None:
                account.status = AccountStatus.AUTH_EXPIRED.value

            await session.execute(
                update(OutboxAction)
                .where(
                    OutboxAction.account_id == claimed.account_id,
                    OutboxAction.state == OutboxActionState.PENDING.value,
                )
                .values(
                    state=OutboxActionState.FAILED.value,
                    finished_at=now,
                    last_error="account authentication expired",
                )
            )

            action = await session.get(OutboxAction, claimed.action_id)
            if action is not None:
                action.state = OutboxActionState.FAILED.value
                action.last_error = str(exc)
                action.lease_expires_at = None
                action.finished_at = now


async def _close(client: ImapClient | None) -> None:
    if client is None:
        return
    try:
        await client.close()
    except Exception:  # noqa: BLE001 - closing must never break the loop
        logger.debug("failed to close IMAP connection", exc_info=True)

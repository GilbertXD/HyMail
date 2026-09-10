"""Tests for the durable sync queue.

Instrumentation notes: ``TrackingFactory`` wraps the fixture's client factory
so a test can observe how many connections a batch opens and in which order
folders were selected. That is how the connection-reuse and priority claims
are checked, rather than by reading logs.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.sync import SyncJob
from hymail_api.domain.enums import SyncJobKind, SyncJobState, SyncPriority
from hymail_api.imap.client import ImapClient
from hymail_api.imap.dto import FetchedMessage, FolderSelection, RemoteFolder
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.services.sync_scheduler import SyncScheduler
from hymail_api.sync.store import get_or_create_folder
from tests.sync.helpers import count_messages, get_missing_flags


@dataclass
class Tracker:
    connects: int = 0
    open_connections: int = 0
    peak_connections: int = 0
    selected: list[str] = field(default_factory=list)


class TrackedClient:
    """Duck-typed ImapClient that records connection and SELECT activity."""

    def __init__(self, inner: ImapClient, tracker: Tracker) -> None:
        self._inner = inner
        self._tracker = tracker
        self._open = False

    async def connect(self) -> None:
        await self._inner.connect()
        self._tracker.connects += 1
        self._tracker.open_connections += 1
        self._tracker.peak_connections = max(
            self._tracker.peak_connections,
            self._tracker.open_connections,
        )
        self._open = True

    async def close(self) -> None:
        if self._open:
            self._tracker.open_connections -= 1
            self._open = False
        await self._inner.close()

    async def list_folders(self) -> list[RemoteFolder]:
        return await self._inner.list_folders()

    async def select_folder(self, folder: str) -> FolderSelection:
        self._tracker.selected.append(folder)
        return await self._inner.select_folder(folder)

    def fetch_messages(self, *args, **kwargs) -> AsyncIterator[FetchedMessage]:
        return self._inner.fetch_messages(*args, **kwargs)


class TrackingFactory:
    def __init__(self, inner: Callable[[], ImapClient]) -> None:
        self._inner = inner
        self.tracker = Tracker()

    def __call__(self, _account) -> ImapClient:  # type: ignore[no-untyped-def]
        return TrackedClient(self._inner(), self.tracker)  # type: ignore[return-value]


def build_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    client_factory,
    **overrides,
) -> SyncScheduler:
    options = {
        "batch_size": 10,
        "max_attempts": 3,
        "lease_seconds": 30.0,
        "backoff_base_seconds": 0.0,
        "max_backoff_seconds": 0.0,
        "poll_interval": 0.01,
    }
    options.update(overrides)
    return SyncScheduler(
        session_factory=session_factory,
        client_factory=client_factory,
        **options,
    )


async def _create_folder(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    name: str,
) -> UUID:
    async with session_factory() as session, session.begin():
        folder = await get_or_create_folder(
            session,
            account_id,
            RemoteFolder(name=name, delimiter="/", flags=frozenset()),
        )
        return folder.id


async def _job_state(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> str | None:
    async with session_factory() as session:
        return await session.scalar(
            select(SyncJob.state).where(SyncJob.id == job_id)
        )


async def _wait_for_job_state(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
    state: SyncJobState,
    deadline_seconds: float = 5.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    current: str | None = None
    while loop.time() < deadline:
        current = await _job_state(session_factory, job_id)
        if current == state.value:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(
        f"job did not reach {state.value!r}; last state was {current!r}"
    )


@pytest_asyncio.fixture
async def scheduler_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[list[SyncScheduler]]:
    """Hands out schedulers and guarantees they are stopped afterwards."""
    created: list[SyncScheduler] = []
    yield created
    for scheduler in created:
        await scheduler.stop()


async def test_job_runs_and_is_recorded_as_success(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    scheduler_factory: list[SyncScheduler],
) -> None:
    mock_server.add_message(message_factory("One"), uid=1)
    folder_id = await _create_folder(session_factory, account_id, "INBOX")

    scheduler = build_scheduler(
        session_factory,
        lambda _account: imap_client_factory(),
    )
    scheduler_factory.append(scheduler)

    job = await scheduler.enqueue_folder(account_id, folder_id)
    await scheduler.drain()

    assert await _job_state(session_factory, job.id) == SyncJobState.SUCCESS.value
    assert await count_messages(session_factory, account_id, "INBOX") == 1


async def test_claim_skips_an_account_that_is_already_running(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    imap_client_factory: Callable[[], ImapClient],
    scheduler_factory: list[SyncScheduler],
) -> None:
    """Account-level mutual exclusion lives in the claim query.

    Checked directly rather than by counting connections: an idle worker keeps
    its connection open, so connection count cannot distinguish "two jobs
    running" from "two workers parked".
    """
    first = await _create_folder(session_factory, account_id, "INBOX")
    second = await _create_folder(session_factory, account_id, "Sent")
    running_id, queued_id = uuid4(), uuid4()
    now = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        session.add(
            SyncJob(
                id=running_id,
                account_id=account_id,
                folder_id=first,
                batch_id=uuid4(),
                state=SyncJobState.RUNNING.value,
                priority=int(SyncPriority.USER),
                attempts=1,
                lease_expires_at=now + timedelta(seconds=60),
            )
        )
        session.add(
            SyncJob(
                id=queued_id,
                account_id=account_id,
                folder_id=second,
                batch_id=uuid4(),
                state=SyncJobState.QUEUED.value,
                priority=int(SyncPriority.USER),
                not_before=now,
            )
        )

    scheduler = build_scheduler(session_factory, imap_client_factory)
    scheduler_factory.append(scheduler)

    # The account is busy, so nothing else may be claimed.
    assert await scheduler._claim_next() is None

    async with session_factory() as session, session.begin():
        job = await session.get(SyncJob, running_id)
        assert job is not None
        job.state = SyncJobState.SUCCESS.value
        job.lease_expires_at = None

    claimed = await scheduler._claim_next()
    assert claimed is not None
    assert claimed.job_id == queued_id


async def test_batch_reuses_one_imap_connection(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    scheduler_factory: list[SyncScheduler],
) -> None:
    names = ["INBOX", "Sent", "Drafts", "Junk"]
    for name in names:
        mock_server.folders.setdefault(name, [])
    folder_ids = [
        await _create_folder(session_factory, account_id, name)
        for name in names
    ]

    tracking = TrackingFactory(imap_client_factory)
    scheduler = build_scheduler(session_factory, tracking)
    scheduler_factory.append(scheduler)

    await scheduler.enqueue_folders(account_id, folder_ids)
    await scheduler.drain()

    # One LOGIN for the whole batch, not one per folder.
    assert tracking.tracker.connects == 1
    assert sorted(tracking.tracker.selected) == sorted(names)


async def test_priority_decides_which_job_runs_first(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    scheduler_factory: list[SyncScheduler],
) -> None:
    """A user-triggered sync must not queue behind a background sweep."""
    for name in ("INBOX", "Sent", "Drafts"):
        mock_server.folders.setdefault(name, [])
    background = await _create_folder(session_factory, account_id, "Drafts")
    user = await _create_folder(session_factory, account_id, "Sent")
    poll = await _create_folder(session_factory, account_id, "INBOX")

    # Insert directly so the claims happen with the scheduler already idle, and
    # in an order where only priority can explain the result.
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        batch = uuid4()
        for folder_id, priority in (
            (background, SyncPriority.RECONCILE),
            (poll, SyncPriority.POLL),
            (user, SyncPriority.USER),
        ):
            session.add(
                SyncJob(
                    account_id=account_id,
                    folder_id=folder_id,
                    batch_id=batch,
                    state=SyncJobState.QUEUED.value,
                    priority=int(priority),
                    not_before=now,
                )
            )

    tracking = TrackingFactory(imap_client_factory)
    scheduler = build_scheduler(session_factory, tracking)
    scheduler_factory.append(scheduler)

    await scheduler.ensure_started()
    await scheduler.drain()

    assert tracking.tracker.selected == ["Sent", "INBOX", "Drafts"]


async def test_expired_lease_is_requeued_but_a_fresh_one_is_not(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    imap_client_factory: Callable[[], ImapClient],
    scheduler_factory: list[SyncScheduler],
) -> None:
    """Crash recovery: an abandoned job must come back, a live one must not."""
    folder_id = await _create_folder(session_factory, account_id, "INBOX")
    now = datetime.now(UTC)
    expired = uuid4()
    fresh = uuid4()

    async with session_factory() as session, session.begin():
        session.add(
            SyncJob(
                id=expired,
                account_id=account_id,
                folder_id=folder_id,
                batch_id=uuid4(),
                state=SyncJobState.RUNNING.value,
                priority=int(SyncPriority.USER),
                attempts=1,
                lease_expires_at=now - timedelta(seconds=5),
            )
        )
        session.add(
            SyncJob(
                id=fresh,
                account_id=account_id,
                folder_id=folder_id,
                batch_id=uuid4(),
                state=SyncJobState.RUNNING.value,
                priority=int(SyncPriority.USER),
                attempts=1,
                lease_expires_at=now + timedelta(seconds=60),
            )
        )

    scheduler = build_scheduler(session_factory, imap_client_factory)
    scheduler_factory.append(scheduler)

    assert await scheduler.recover_stale_jobs() == 1

    assert await _job_state(session_factory, expired) == (
        SyncJobState.QUEUED.value
    )
    assert await _job_state(session_factory, fresh) == (
        SyncJobState.RUNNING.value
    )


async def test_cancelling_a_batch_cancels_its_queued_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    imap_client_factory: Callable[[], ImapClient],
    scheduler_factory: list[SyncScheduler],
) -> None:
    folder_ids = [
        await _create_folder(session_factory, account_id, name)
        for name in ("INBOX", "Sent", "Drafts")
    ]
    batch = uuid4()
    now = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        for folder_id in folder_ids:
            session.add(
                SyncJob(
                    account_id=account_id,
                    folder_id=folder_id,
                    batch_id=batch,
                    state=SyncJobState.QUEUED.value,
                    priority=int(SyncPriority.USER),
                    not_before=now,
                )
            )

    scheduler = build_scheduler(session_factory, imap_client_factory)
    scheduler_factory.append(scheduler)

    assert await scheduler.cancel_batch(batch) == 3

    summary = await scheduler.batch_summary(batch)
    assert summary is not None
    assert summary.cancelled == 3
    assert summary.state.value == "cancelled"


async def test_reconcile_job_runs_the_reconcile_path(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    scheduler_factory: list[SyncScheduler],
) -> None:
    """A job's kind selects sync or reconcile, not just which folder."""
    for uid, subject in enumerate(["One", "Two"], start=1):
        mock_server.add_message(message_factory(subject), uid=uid)
    folder_id = await _create_folder(session_factory, account_id, "INBOX")

    scheduler = build_scheduler(
        session_factory,
        lambda _account: imap_client_factory(),
    )
    scheduler_factory.append(scheduler)

    await scheduler.enqueue_folder(account_id, folder_id)
    await scheduler.drain()

    mock_server.remove_message(1)

    job = await scheduler.enqueue_folder(
        account_id,
        folder_id,
        kind=SyncJobKind.RECONCILE,
    )
    await scheduler.drain()

    assert await _job_state(session_factory, job.id) == (
        SyncJobState.SUCCESS.value
    )
    assert await get_missing_flags(session_factory, account_id, "INBOX") == [
        (1, True),
        (2, False),
    ]


async def test_cancelling_a_running_job_stops_it(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    scheduler_factory: list[SyncScheduler],
) -> None:
    """Cancellation still works now that jobs run inside the queue."""
    for index in range(1, 21):
        mock_server.add_message(
            message_factory(f"Slow {index:02d}"),
            uid=index,
        )
    mock_server.scenario.command_delay = 0.05
    folder_id = await _create_folder(session_factory, account_id, "INBOX")

    scheduler = build_scheduler(
        session_factory,
        lambda _account: imap_client_factory(),
        batch_size=5,
    )
    scheduler_factory.append(scheduler)

    job = await scheduler.enqueue_folder(account_id, folder_id)
    await _wait_for_job_state(
        session_factory,
        job.id,
        SyncJobState.RUNNING,
    )

    cancelled = await scheduler.cancel_folder(account_id, folder_id)
    mock_server.scenario.command_delay = 0.0

    assert cancelled == 1
    await _wait_for_job_state(
        session_factory,
        job.id,
        SyncJobState.CANCELLED,
    )

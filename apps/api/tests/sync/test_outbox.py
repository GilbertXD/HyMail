"""The durable outbox: local flag changes finding their way to the server."""

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.services.outbox import OutboxDispatcher
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import get_account_status


@pytest_asyncio.fixture
async def dispatchers(
    session_factory: async_sessionmaker[AsyncSession],
) -> Sequence[OutboxDispatcher]:
    """Hands out dispatchers and stops them before the engine is disposed.

    Depending on ``session_factory`` is what orders the teardown: a worker
    still querying after the engine closes logs "Event loop is closed".
    """
    created: list[OutboxDispatcher] = []
    yield created
    for dispatcher in created:
        await dispatcher.stop()


def build_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    imap_client_factory: Callable[[], ImapClient],
    **overrides,
) -> OutboxDispatcher:
    options = {
        "max_attempts": 3,
        "lease_seconds": 30.0,
        "backoff_base_seconds": 0.0,
        "max_backoff_seconds": 0.0,
        "poll_interval": 0.01,
    }
    options.update(overrides)
    return OutboxDispatcher(
        session_factory=session_factory,
        client_factory=lambda _account: imap_client_factory(),
        **options,
    )


async def _seed_message(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    imap_client_factory: Callable[[], ImapClient],
    mock_server: MockImapServer,
    message_factory: Callable[[str, str], bytes],
) -> Message:
    mock_server.add_message(message_factory("One"), uid=1)
    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=1,
    )
    await engine.sync_folder(account_id, "INBOX")

    async with session_factory() as session:
        message = await session.scalar(
            select(Message).where(Message.account_id == account_id)
        )
    assert message is not None
    return message


async def _mark_locally_read(
    session_factory: async_sessionmaker[AsyncSession],
    message_id: UUID,
    value: bool = True,
) -> None:
    """The optimistic half: the UI already shows the new value."""
    async with session_factory() as session, session.begin():
        message = await session.get(Message, message_id)
        assert message is not None
        message.is_read = value


async def _count_actions(
    session_factory: async_sessionmaker[AsyncSession],
    state: OutboxActionState | None = None,
) -> int:
    async with session_factory() as session:
        statement = select(func.count()).select_from(OutboxAction)
        if state is not None:
            statement = statement.where(OutboxAction.state == state.value)
        return int(await session.scalar(statement) or 0)


async def _single_action(
    session_factory: async_sessionmaker[AsyncSession],
) -> OutboxAction:
    async with session_factory() as session:
        action = await session.scalar(select(OutboxAction))
    assert action is not None
    return action


async def test_flag_change_reaches_the_server(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.MARK_READ,
        value=True,
    )
    await dispatcher.drain()

    assert mock_server.folders["INBOX"][0].flags == ["\\Seen"]
    assert await _count_actions(session_factory, OutboxActionState.SUCCESS) == 1


async def test_repeating_the_same_toggle_is_a_no_op(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    first = await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.MARK_READ,
        value=True,
    )
    second = await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.MARK_READ,
        value=True,
    )

    assert first is not None
    assert second is None
    assert await _count_actions(session_factory) == 1


async def test_superseding_toggle_sends_only_the_latest_value(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    """Read then unread must not send two contradictory writes."""
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    for value in (True, False):
        await dispatcher.enqueue_flag_change(
            account_id=account_id,
            message_id=message.id,
            folder_id=message.folder_id,
            uid=message.uid,
            action_type=OutboxActionType.MARK_READ,
            value=value,
        )

    assert await _count_actions(session_factory) == 1
    await dispatcher.drain()

    assert mock_server.folders["INBOX"][0].flags == []
    assert await _count_actions(session_factory, OutboxActionState.SUCCESS) == 1


async def test_expired_lease_is_requeued(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    action = await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.MARK_READ,
        value=True,
    )
    assert action is not None

    async with session_factory() as session, session.begin():
        stored = await session.get(OutboxAction, action.id)
        assert stored is not None
        stored.state = OutboxActionState.INFLIGHT.value
        stored.attempts = 1
        stored.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)

    assert await dispatcher.recover_stale_actions() == 1
    assert await _count_actions(session_factory, OutboxActionState.PENDING) == 1


async def test_outbox_waits_while_the_account_is_syncing(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    """One IMAP connection per account, even across the two services."""
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.MARK_READ,
        value=True,
    )

    async with session_factory() as session, session.begin():
        session.add(
            SyncJob(
                account_id=account_id,
                folder_id=message.folder_id,
                batch_id=uuid4(),
                state=SyncJobState.RUNNING.value,
                priority=0,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
            )
        )

    assert await dispatcher._claim_next() is None


async def test_discard_rolls_the_local_row_back(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    """flags_json holds the server's view, which is what to restore."""
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    await _mark_locally_read(session_factory, message.id, True)

    action = await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.MARK_READ,
        value=True,
    )
    assert action is not None

    assert await dispatcher.discard(action.id) is True

    async with session_factory() as session:
        stored = await session.get(Message, message.id)
        assert stored is not None
        assert stored.is_read is False

    assert await _count_actions(session_factory, OutboxActionState.ABANDONED) == 1


async def test_retry_puts_a_failed_action_back_in_the_queue(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    action = await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.STAR,
        value=True,
    )
    assert action is not None

    async with session_factory() as session, session.begin():
        stored = await session.get(OutboxAction, action.id)
        assert stored is not None
        stored.state = OutboxActionState.FAILED.value
        stored.last_error = "boom"

    assert await dispatcher.retry(action.id) is True
    await dispatcher.drain()

    assert mock_server.folders["INBOX"][0].flags == ["\\Flagged"]


async def test_auth_failure_pauses_the_account(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.MARK_READ,
        value=True,
    )
    await dispatcher.drain()

    mock_server.scenario.auth_failures = 99
    await dispatcher.enqueue_flag_change(
        account_id=account_id,
        message_id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        action_type=OutboxActionType.STAR,
        value=True,
    )
    await dispatcher.drain()

    assert await get_account_status(session_factory, account_id) == (
        AccountStatus.AUTH_EXPIRED.value
    )
    assert await _count_actions(session_factory, OutboxActionState.FAILED) == 1


async def test_pending_actions_are_reported_per_message(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
    dispatchers: list[OutboxDispatcher],
) -> None:
    message = await _seed_message(
        session_factory,
        account_id,
        imap_client_factory,
        mock_server,
        message_factory,
    )
    dispatcher = build_dispatcher(session_factory, imap_client_factory)
    dispatchers.append(dispatcher)

    async with (
        session_factory() as session,
        session.begin(),
    ):
        session.add(
            OutboxAction(
                account_id=account_id,
                message_id=message.id,
                folder_id=message.folder_id,
                uid=message.uid,
                type=OutboxActionType.MARK_READ.value,
                payload_json={"value": True},
                state=OutboxActionState.PENDING.value,
            )
        )

    pending = await dispatcher.pending_message_ids(account_id)
    assert pending == {message.id: OutboxActionState.PENDING.value}


async def test_drain_returns_when_nothing_is_queued(
    session_factory: async_sessionmaker[AsyncSession],
    dispatchers: list[OutboxDispatcher],
) -> None:
    dispatcher = build_dispatcher(session_factory, lambda: None)  # type: ignore[arg-type]
    dispatchers.append(dispatcher)
    await asyncio.wait_for(dispatcher.drain(1.0), timeout=2.0)

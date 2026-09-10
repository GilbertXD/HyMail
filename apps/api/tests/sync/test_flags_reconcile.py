"""Flag reconciliation: aligning local read/starred with server FLAGS."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.message import Message
from hymail_api.db.models.outbox import OutboxAction
from hymail_api.domain.enums import OutboxActionState, OutboxActionType
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import get_flag_states


def build_engine(
    session_factory: async_sessionmaker[AsyncSession],
    imap_client_factory: Callable[[], ImapClient],
) -> SyncEngine:
    return SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=1,
    )


async def _queue_flag_change(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    uid: int,
    *,
    action_type: OutboxActionType = OutboxActionType.MARK_READ,
) -> None:
    """Queue a flag change and apply the optimistic local update, as the API does.

    Both halves matter: the point of the conflict rule is that the local row
    already says one thing while the server still says another.
    """
    async with session_factory() as session, session.begin():
        message = await session.scalar(
            select(Message).where(
                Message.account_id == account_id,
                Message.uid == uid,
            )
        )
        assert message is not None

        desired = True
        if action_type is OutboxActionType.MARK_READ:
            message.is_read = desired
        else:
            message.is_starred = desired

        session.add(
            OutboxAction(
                account_id=account_id,
                message_id=message.id,
                folder_id=message.folder_id,
                uid=uid,
                type=action_type.value,
                payload_json={"value": desired},
                state=OutboxActionState.PENDING.value,
            )
        )


async def test_new_mail_arrives_with_its_flags(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(
        message_factory("Read one"),
        uid=1,
        flags=["\\Seen"],
    )
    mock_server.add_message(message_factory("Unread two"), uid=2)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    assert await get_flag_states(session_factory, account_id, "INBOX") == [
        (1, True, False),
        (2, False, False),
    ]


async def test_reconcile_pulls_flags_changed_elsewhere(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """Another device marking mail read has to reach this copy."""
    for uid in (1, 2):
        mock_server.add_message(message_factory(f"Msg {uid}"), uid=uid)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")
    assert await get_flag_states(session_factory, account_id, "INBOX") == [
        (1, False, False),
        (2, False, False),
    ]

    mock_server.folders["INBOX"][0].flags.extend(["\\Seen", "\\Flagged"])
    mock_server.folders["INBOX"][1].flags.append("\\Seen")

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.flags_changed == 2
    assert await get_flag_states(session_factory, account_id, "INBOX") == [
        (1, True, True),
        (2, True, False),
    ]


async def test_reconcile_does_not_undo_a_queued_local_change(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """The optimistic click must win until the server has actually heard it.

    Marking a message read locally queues a write; the server still reports it
    unread. Trusting the server here would silently revert the user's action.
    """
    for uid in (1, 2):
        mock_server.add_message(message_factory(f"Msg {uid}"), uid=uid)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    await _queue_flag_change(session_factory, account_id, 1)

    mock_server.folders["INBOX"][1].flags.append("\\Seen")

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.flags_changed == 1
    states = await get_flag_states(session_factory, account_id, "INBOX")
    # UID 1 keeps the optimistic value; UID 2 follows the server.
    assert states == [(1, True, False), (2, True, False)]


async def test_reconcile_leaves_a_message_the_server_no_longer_has(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(message_factory("One"), uid=1)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.remove_message(1)

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.flags_changed == 0
    assert await get_flag_states(session_factory, account_id, "INBOX") == [
        (1, False, False)
    ]

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.domain.enums import SyncState
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import count_messages, get_cursor_values, get_message_subjects


async def test_uidvalidity_change_triggers_resync(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(message_factory("Old One"), uid=1)
    mock_server.add_message(message_factory("Old Two"), uid=2)

    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=1,
    )
    await engine.sync_folder(account_id, "INBOX")
    assert await count_messages(session_factory, account_id, "INBOX") == 2

    mock_server.clear_mailbox()
    mock_server.set_uidvalidity(42)
    mock_server.add_message(message_factory("New One"), uid=1)

    result = await engine.sync_folder(account_id, "INBOX")

    assert result.state is SyncState.IDLE
    assert result.fetched_count == 1
    assert result.uidvalidity == 42
    assert await count_messages(session_factory, account_id, "INBOX") == 1
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == ["New One"]

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[0] == SyncState.IDLE.value
    assert cursor[1] == 1
    assert cursor[2] == 42
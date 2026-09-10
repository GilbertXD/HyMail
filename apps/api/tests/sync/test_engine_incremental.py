from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.domain.enums import SyncState
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import count_messages, get_cursor_values, get_message_subjects


async def test_incremental_sync_only_fetches_new_uids(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(message_factory("One"), uid=1)
    mock_server.add_message(message_factory("Two"), uid=2)

    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=1,
    )
    first = await engine.sync_folder(account_id, "INBOX")
    assert first.fetched_count == 2
    assert first.last_uid == 2

    mock_server.add_message(message_factory("Three"), uid=3)
    second = await engine.sync_folder(account_id, "INBOX")

    assert second.state is SyncState.IDLE
    assert second.fetched_count == 1
    assert second.last_uid == 3
    assert await count_messages(session_factory, account_id, "INBOX") == 3
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == ["One", "Two", "Three"]

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[1] == 3
    assert cursor[2] == 1
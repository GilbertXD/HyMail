from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import count_messages, get_cursor_values


async def test_initial_sync_1k_messages(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    for index in range(1, 1001):
        mock_server.add_message(
            message_factory(f"Scale {index:04d}"),
            uid=index,
        )

    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=100,
        max_attempts=1,
    )
    result = await engine.sync_folder(account_id, "INBOX")

    assert result.fetched_count == 1000
    assert result.last_uid == 1000
    assert await count_messages(session_factory, account_id, "INBOX") == 1000

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[0] == "idle"
    assert cursor[1] == 1000
    assert cursor[2] == 1
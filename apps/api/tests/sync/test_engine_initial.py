from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.domain.enums import SyncState
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import (
    count_messages,
    get_cursor_values,
    get_event_values,
    get_message_subjects,
)


async def test_initial_sync_persists_messages_and_cursor(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(message_factory("One"), uid=1)
    mock_server.add_message(message_factory("Two"), uid=2)
    mock_server.add_message(message_factory("Three"), uid=3)

    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=2,
        max_attempts=1,
    )
    result = await engine.sync_folder(account_id, "INBOX")

    assert result.state is SyncState.IDLE
    assert result.fetched_count == 3
    assert result.last_uid == 3
    assert result.uidvalidity == 1
    assert result.uidnext == 4

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[0] == SyncState.IDLE.value
    assert cursor[1] == 3
    assert cursor[2] == 1
    assert cursor[3] == 4
    assert cursor[4] == 0
    assert cursor[5] is None

    assert await count_messages(session_factory, account_id, "INBOX") == 3
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == ["One", "Two", "Three"]

    events = await get_event_values(session_factory, account_id)
    assert ("sync.start", "initial_sync", None, None, 0) in events
    assert ("sync.completed", "idle", None, None, 3) in events
from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.imap.client import ImapClient
from hymail_api.imap.errors import ImapAuthenticationError
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import (
    count_messages,
    get_account_status,
    get_cursor_values,
    get_event_values,
)


async def test_auth_failure_marks_auth_expired(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
) -> None:
    mock_server.scenario.auth_failures = 1
    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=3,
    )

    with pytest.raises(ImapAuthenticationError):
        await engine.sync_folder(account_id, "INBOX")

    assert await get_account_status(session_factory, account_id) == "auth_expired"

    events = await get_event_values(session_factory, account_id)
    assert any(event[0] == "sync.auth_expired" for event in events)


async def test_connection_failure_retries_and_recovers(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(message_factory("One"), uid=1)
    mock_server.scenario.disconnect_on_fetch = True

    async def recovery_sleep(_: float) -> None:
        mock_server.scenario.disconnect_on_fetch = False

    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=2,
        backoff_base_seconds=0.0,
        sleep_func=recovery_sleep,
    )
    result = await engine.sync_folder(account_id, "INBOX")

    assert result.fetched_count == 1
    assert await count_messages(session_factory, account_id, "INBOX") == 1

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[0] == "idle"
    assert cursor[4] == 0

    events = await get_event_values(session_factory, account_id)
    assert any(event[0] == "sync.backoff" for event in events)
    assert any(event[0] == "sync.completed" for event in events)


async def test_rate_limit_retries_and_recovers(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(message_factory("One"), uid=1)
    mock_server.scenario.rate_limit_after_commands = 2

    async def recovery_sleep(_: float) -> None:
        mock_server.scenario.rate_limit_after_commands = None

    engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=2,
        backoff_base_seconds=0.0,
        sleep_func=recovery_sleep,
    )
    result = await engine.sync_folder(account_id, "INBOX")

    assert result.fetched_count == 1

    events = await get_event_values(session_factory, account_id)
    assert any(event[0] == "sync.backoff" for event in events)
    assert any(event[0] == "sync.completed" for event in events)
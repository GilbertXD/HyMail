from email.mime.text import MIMEText

import pytest

from hymail_api.imap.client import ImapClient
from hymail_api.imap.errors import (
    ImapAuthenticationError,
    ImapConnectionError,
    ImapFetchInterruptedError,
    ImapRateLimitError,
)
from hymail_api.imap.mock_server import MockImapScenario, MockImapServer


def make_raw_message(subject: str, body: str = "hello") -> bytes:
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    message["Message-ID"] = f"<{subject}@example.com>"
    message["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
    return message.as_bytes()


@pytest.fixture
async def server() -> MockImapServer:
    mock_server = MockImapServer(
        MockImapScenario(username="user@example.com", password="secret")
    )
    await mock_server.start()
    yield mock_server
    await mock_server.stop()


async def test_client_lists_folders_and_fetches_messages(
    server: MockImapServer,
) -> None:
    server.add_message(make_raw_message("One"), uid=1)
    server.add_message(make_raw_message("Two"), uid=2)

    client = ImapClient(
        host="127.0.0.1",
        port=server.port,
        ssl=False,
        username="user@example.com",
        password="secret",
        timeout=2.0,
    )
    await client.connect()

    folders = await client.list_folders()
    assert [folder.name for folder in folders] == ["INBOX", "Sent"]

    selection = await client.select_folder("INBOX")
    assert selection.exists == 2
    assert selection.uidvalidity == 1
    assert selection.uidnext == 3

    messages = [message async for message in client.fetch_messages("INBOX", 1)]
    assert [message.uid for message in messages] == [1, 2]
    assert messages[0].parsed.subject == "One"
    assert messages[0].parsed.body_text is not None
    assert "hello" in messages[0].parsed.body_text

    await client.close()


async def test_client_fetches_incrementally(server: MockImapServer) -> None:
    server.add_message(make_raw_message("One"), uid=1)
    server.add_message(make_raw_message("Two"), uid=2)
    server.add_message(make_raw_message("Three"), uid=3)

    client = ImapClient(
        host="127.0.0.1",
        port=server.port,
        ssl=False,
        username="user@example.com",
        password="secret",
        timeout=2.0,
    )
    await client.connect()

    messages = [message async for message in client.fetch_messages("INBOX", 3)]
    assert [message.uid for message in messages] == [3]

    await client.close()


async def test_client_maps_auth_failure() -> None:
    mock_server = MockImapServer(
        MockImapScenario(
            username="user@example.com",
            password="secret",
            auth_failures=1,
        )
    )
    await mock_server.start()
    try:
        client = ImapClient(
            host="127.0.0.1",
            port=mock_server.port,
            ssl=False,
            username="user@example.com",
            password="secret",
            timeout=2.0,
        )
        with pytest.raises(ImapAuthenticationError):
            await client.connect()
    finally:
        await mock_server.stop()


async def test_client_maps_rate_limit(server: MockImapServer) -> None:
    server.scenario.rate_limit_after_commands = 2
    client = ImapClient(
        host="127.0.0.1",
        port=server.port,
        ssl=False,
        username="user@example.com",
        password="secret",
        timeout=2.0,
    )
    with pytest.raises(ImapRateLimitError):
        await client.connect()


async def test_client_maps_fetch_interruption(server: MockImapServer) -> None:
    server.add_message(make_raw_message("One"), uid=1)
    server.scenario.disconnect_on_fetch = True

    client = ImapClient(
        host="127.0.0.1",
        port=server.port,
        ssl=False,
        username="user@example.com",
        password="secret",
        timeout=1.0,
    )
    await client.connect()

    with pytest.raises((ImapFetchInterruptedError, ImapConnectionError)):
        _ = [message async for message in client.fetch_messages("INBOX", 1)]


async def test_server_reports_changed_uidvalidity(
    server: MockImapServer,
) -> None:
    client = ImapClient(
        host="127.0.0.1",
        port=server.port,
        ssl=False,
        username="user@example.com",
        password="secret",
        timeout=2.0,
    )
    await client.connect()

    first = await client.select_folder("INBOX")
    server.set_uidvalidity(42)
    second = await client.select_folder("INBOX")

    assert first.uidvalidity == 1
    assert second.uidvalidity == 42
    await client.close()


async def test_client_maps_disconnect_after_command(
    server: MockImapServer,
) -> None:
    server.scenario.disconnect_after_commands = 3
    client = ImapClient(
        host="127.0.0.1",
        port=server.port,
        ssl=False,
        username="user@example.com",
        password="secret",
        timeout=0.5,
    )
    await client.connect()

    with pytest.raises(ImapConnectionError):
        await client.list_folders()
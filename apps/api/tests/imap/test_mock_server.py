import pytest
from aioimaplib import IMAP4

from hymail_api.imap.mock_server import MockImapScenario, MockImapServer


@pytest.fixture
async def server() -> MockImapServer:
    scenario = MockImapScenario(
        username="user@example.com",
        password="secret",
    )
    mock_server = MockImapServer(scenario)
    await mock_server.start()
    yield mock_server
    await mock_server.stop()


async def test_mock_server_login_list_and_select(server: MockImapServer) -> None:
    client = IMAP4(host="127.0.0.1", port=server.port, timeout=2.0)
    await client.wait_hello_from_server()
    response = await client.login("user@example.com", "secret")
    assert response.result == "OK"

    response = await client.list('""', '"*"')
    assert response.result == "OK"
    assert any(b"INBOX" in line for line in response.lines)

    response = await client.select('"INBOX"')
    assert response.result == "OK"
    assert any(b"UIDVALIDITY" in line for line in response.lines)

    await client.logout()


async def test_mock_server_speaks_modified_utf7(server: MockImapServer) -> None:
    """The wire carries modified UTF-7, not raw UTF-8.

    Checked with aioimaplib directly so the assertion does not depend on our
    own client's codec.
    """
    server.add_message(
        b"Subject: x\r\n\r\nbody",
        mailbox="已删除",
        uid=1,
    )

    client = IMAP4(host="127.0.0.1", port=server.port, timeout=2.0)
    await client.wait_hello_from_server()
    await client.login("user@example.com", "secret")

    response = await client.list('""', '"*"')
    assert any(b'"&XfJSIJZk-"' in line for line in response.lines)

    response = await client.select('"&XfJSIJZk-"')
    assert response.result == "OK"
    assert any(b"1 EXISTS" in line for line in response.lines)

    await client.logout()
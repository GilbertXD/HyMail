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
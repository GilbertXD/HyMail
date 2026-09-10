from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.folder import Folder
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.imap.utf7 import encode_mailbox


async def test_refresh_folders_heals_legacy_encoded_names(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server: MockImapServer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Regression: refreshing a pre-upgrade database returned HTTP 500.

    The stored folder still carried its raw wire name. Renaming it and then
    looking it up in the same transaction used to miss the row, insert a
    duplicate, and blow up on the (account_id, name) unique constraint — which
    reached the browser as a bare "Failed to fetch" because the 500 response
    carried no CORS headers.

    Every folder but the renamed one must already exist locally: an insert
    flushes the session, and a stray flush would mask the stale read.
    """
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201
    account_id = UUID(create_response.json()["id"])

    mock_server.add_message(
        b"Subject: legacy\r\n\r\nbody",
        mailbox="已删除",
        uid=1,
    )
    async with session_factory() as session, session.begin():
        for name in ("INBOX", "Sent", encode_mailbox("已删除")):
            session.add(Folder(account_id=account_id, name=name))

    response = await client.post("/api/v1/folders/refresh")

    assert response.status_code == 200
    names = [folder["name"] for folder in response.json()]
    assert "已删除" in names
    assert encode_mailbox("已删除") not in names


async def test_refresh_folders_is_repeatable(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server: MockImapServer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201
    account_id = UUID(create_response.json()["id"])

    mock_server.add_message(
        b"Subject: legacy\r\n\r\nbody",
        mailbox="已删除",
        uid=1,
    )
    async with session_factory() as session, session.begin():
        for name in ("INBOX", "Sent", encode_mailbox("已删除")):
            session.add(Folder(account_id=account_id, name=name))

    first = await client.post("/api/v1/folders/refresh")
    second = await client.post("/api/v1/folders/refresh")

    assert first.status_code == 200
    assert second.status_code == 200
    assert sorted(f["name"] for f in first.json()) == sorted(
        f["name"] for f in second.json()
    )

"""Whole-mailbox sync over the API."""

import asyncio
from email.mime.text import MIMEText
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.folder import Folder


def _message(subject: str) -> bytes:
    message = MIMEText("body", "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    # Real mail carries one, and it is the only thing move detection can use.
    message["Message-ID"] = f"<{subject}@example.com>"
    return message.as_bytes()


async def _wait_for_batch(
    client: AsyncClient,
    batch_id: str,
    deadline_seconds: float = 15.0,
) -> dict[str, object]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    body: dict[str, object] = {}
    while loop.time() < deadline:
        response = await client.get(f"/api/v1/sync/batches/{batch_id}")
        assert response.status_code == 200
        body = response.json()
        if body["state"] not in {"queued", "running"}:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"batch did not settle; last state {body!r}")


async def test_trigger_all_syncs_every_remote_folder(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    # Two mailboxes with mail in each, so a partial run is visible.
    mock_server.add_message(_message("Inbox one"), mailbox="INBOX", uid=1)
    mock_server.add_message(_message("Sent one"), mailbox="Sent", uid=1)

    refresh_response = await client.post("/api/v1/folders/refresh")
    assert refresh_response.status_code == 200

    trigger_response = await client.post(
        "/api/v1/sync/trigger-all",
        json={},
    )
    assert trigger_response.status_code == 202
    queued = trigger_response.json()
    assert queued["queued"] == 2

    summary = await _wait_for_batch(client, queued["batch_id"])

    assert summary["state"] == "completed"
    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["failed"] == 0

    folders_response = await client.get("/api/v1/folders")
    folders = {f["name"]: f for f in folders_response.json()}
    assert folders["INBOX"]["message_count"] == 1
    assert folders["Sent"]["message_count"] == 1


async def test_trigger_all_skips_folders_the_server_does_not_have(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Leftovers from a previously configured mailbox must not be attempted.

    They would each fail with "mailbox not found", which the UI would show as
    a wall of errors for folders the user cannot even use.
    """
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201
    account_id = UUID(create_response.json()["id"])

    refresh_response = await client.post("/api/v1/folders/refresh")
    assert refresh_response.status_code == 200

    # A local folder the mock server will never list.
    async with session_factory() as session, session.begin():
        session.add(Folder(account_id=account_id, name="Ghost Folder"))

    trigger_response = await client.post("/api/v1/sync/trigger-all", json={})
    assert trigger_response.status_code == 202
    body = trigger_response.json()

    assert body["queued"] == 2
    assert body["skipped"] == 1

    summary = await _wait_for_batch(client, body["batch_id"])
    assert summary["total"] == 2
    assert summary["failed"] == 0


async def test_reconcile_flags_messages_deleted_on_the_server(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    mock_server.add_message(_message("One"), mailbox="INBOX", uid=1)
    mock_server.add_message(_message("Two"), mailbox="INBOX", uid=2)

    refresh_response = await client.post("/api/v1/folders/refresh")
    assert refresh_response.status_code == 200

    first = await client.post("/api/v1/sync/trigger-all", json={})
    await _wait_for_batch(client, first.json()["batch_id"])

    mock_server.remove_message(1)

    reconcile = await client.post(
        "/api/v1/sync/reconcile",
        json={"folder_names": ["INBOX"]},
    )
    assert reconcile.status_code == 202
    assert reconcile.json()["queued"] == 1

    summary = await _wait_for_batch(client, reconcile.json()["batch_id"])
    assert summary["state"] == "completed"
    assert summary["success"] == 1

    messages = (await client.get("/api/v1/messages")).json()
    by_uid = {message["uid"]: message for message in messages}
    assert by_uid[1]["remote_missing"] is True
    assert by_uid[2]["remote_missing"] is False

    # The message is flagged rather than dropped, so the change is visible.
    assert len(messages) == 2

    events = (await client.get("/api/v1/sync/events")).json()
    assert any(event["event_type"] == "sync.reconcile" for event in events)


async def test_reconcile_reports_where_a_message_went(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    """A whole-account reconcile explains a move in a single pass.

    The source folder is processed first and only learns the message is gone;
    the destination then fetches it and fills in the explanation.
    """
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    mock_server.add_message(_message("Moving"), mailbox="INBOX", uid=1)
    mock_server.add_message(_message("Keeper"), mailbox="INBOX", uid=2)

    refresh_response = await client.post("/api/v1/folders/refresh")
    assert refresh_response.status_code == 200

    first = await client.post("/api/v1/sync/trigger-all", json={})
    await _wait_for_batch(client, first.json()["batch_id"])

    mock_server.move_message(1, from_mailbox="INBOX", to_mailbox="Sent")

    reconcile = await client.post("/api/v1/sync/reconcile", json={})
    assert reconcile.status_code == 202
    summary = await _wait_for_batch(client, reconcile.json()["batch_id"])
    assert summary["state"] == "completed"

    messages = (await client.get("/api/v1/messages")).json()
    by_key = {(m["folder_name"], m["uid"]): m for m in messages}

    ghost = by_key[("INBOX", 1)]
    assert ghost["remote_missing"] is True
    assert ghost["moved_to_folder_name"] == "Sent"

    # The keeper is untouched, and the message is also live in its new home.
    assert by_key[("INBOX", 2)]["remote_missing"] is False
    assert by_key[("INBOX", 2)]["moved_to_folder_name"] is None
    assert any(
        message["folder_name"] == "Sent" and message["remote_missing"] is False
        for message in messages
    )

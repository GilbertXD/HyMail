import asyncio
from email.mime.text import MIMEText

from httpx import AsyncClient


def make_raw_message(subject: str) -> bytes:
    message = MIMEText("hello", "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    return message.as_bytes()


async def _wait_until_idle(
    client: AsyncClient,
    folder: str = "INBOX",
) -> dict[str, object]:
    for _ in range(80):
        response = await client.get(
            "/api/v1/sync/status",
            params={"folder": folder},
        )
        assert response.status_code == 200
        body = response.json()
        if not body["running"] and body["state"] in {"idle", "error"}:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("sync did not finish in time")


async def test_trigger_sync_and_query_results(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    # The queue is keyed by folder id, so folders have to be discovered first.
    refresh_response = await client.post("/api/v1/folders/refresh")
    assert refresh_response.status_code == 200

    mock_server.add_message(make_raw_message("One"), uid=1)

    trigger_response = await client.post(
        "/api/v1/sync/trigger",
        json={"folder": "INBOX"},
    )
    assert trigger_response.status_code == 202

    status = await _wait_until_idle(client)
    assert status["state"] == "idle"
    assert status["last_uid"] == 1

    folders_response = await client.get("/api/v1/folders")
    assert folders_response.status_code == 200
    folders = folders_response.json()
    inbox = next(folder for folder in folders if folder["name"] == "INBOX")

    messages_response = await client.get(
        f"/api/v1/folders/{inbox['id']}/messages"
    )
    assert messages_response.status_code == 200
    messages = messages_response.json()
    assert len(messages) == 1
    assert messages[0]["subject"] == "One"

    detail_response = await client.get(f"/api/v1/messages/{messages[0]['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["subject"] == "One"
    assert "hello" in detail["body_text"]

    events_response = await client.get("/api/v1/sync/events")
    assert events_response.status_code == 200
    event_types = {
        event["event_type"] for event in events_response.json()
    }
    assert "sync.start" in event_types
    assert "sync.completed" in event_types


async def test_trigger_unknown_folder_returns_404(
    client: AsyncClient,
    account_payload: dict[str, object],
) -> None:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    response = await client.post(
        "/api/v1/sync/trigger",
        json={"folder": "Nowhere"},
    )

    assert response.status_code == 404
    assert "Nowhere" in response.json()["detail"]


async def test_cancel_without_running_sync_cancels_nothing(
    client: AsyncClient,
    account_payload: dict[str, object],
) -> None:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    response = await client.post(
        "/api/v1/sync/cancel",
        json={"folder": "INBOX"},
    )
    assert response.status_code == 200
    assert response.json() == {"cancelled": 0}
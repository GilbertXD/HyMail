"""The metrics endpoint: what the sync pipeline actually did."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.folder import Folder
from hymail_api.db.models.sync import SyncJob
from hymail_api.domain.enums import SyncJobState
from tests.api.helpers import message_bytes, wait_for_batch


async def _seed_and_sync(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> UUID:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    mock_server.add_message(message_bytes("One"), mailbox="INBOX", uid=1)
    mock_server.add_message(message_bytes("Two"), mailbox="INBOX", uid=2)
    mock_server.add_message(message_bytes("Sent one"), mailbox="Sent", uid=1)

    refresh = await client.post("/api/v1/folders/refresh")
    assert refresh.status_code == 200

    trigger = await client.post("/api/v1/sync/trigger-all", json={})
    await wait_for_batch(client, trigger.json()["batch_id"])

    return UUID((await client.get("/api/v1/accounts/current")).json()["id"])


async def test_metrics_report_what_the_syncs_did(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    await _seed_and_sync(client, account_payload, mock_server)

    response = await client.get("/api/v1/metrics")

    assert response.status_code == 200
    body = response.json()

    # One run per remote folder, and every message accounted for.
    assert body["runs"] == 2
    assert body["failures"] == 0
    assert body["failure_rate"] == 0
    assert body["retries"] == 0
    assert body["fetched"] == 3

    # Durations used to be a parameter nobody ever filled in.
    assert body["avg_duration_ms"] is not None
    assert body["p95_duration_ms"] is not None

    by_name = {item["folder_name"]: item for item in body["folders"]}
    assert by_name["INBOX"]["fetched"] == 2
    assert by_name["Sent"]["fetched"] == 1
    assert by_name["INBOX"]["runs"] == 1
    assert by_name["INBOX"]["last_sync_at"] is not None


async def test_metrics_count_retries_and_failures(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = await _seed_and_sync(client, account_payload, mock_server)

    async with session_factory() as session, session.begin():
        folder_id = await session.scalar(
            select(Folder.id).where(
                Folder.account_id == account_id,
                Folder.name == "INBOX",
            )
        )
        assert folder_id is not None
        session.add(
            SyncJob(
                account_id=account_id,
                folder_id=folder_id,
                batch_id=uuid4(),
                state=SyncJobState.FAILED.value,
                priority=0,
                attempts=3,
                last_error="mailbox unavailable",
            )
        )

    body = (await client.get("/api/v1/metrics")).json()

    # Two more attempts on one job than the baseline.
    assert body["retries"] == 2
    assert body["failures"] == 1
    assert body["runs"] == 3
    assert body["failure_rate"] == pytest.approx(1 / 3)

    inbox = next(
        item for item in body["folders"] if item["folder_name"] == "INBOX"
    )
    assert inbox["failures"] == 1
    assert inbox["retries"] == 2
    assert inbox["last_error"] == "mailbox unavailable"


async def test_metrics_window_excludes_older_runs(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = await _seed_and_sync(client, account_payload, mock_server)

    async with session_factory() as session, session.begin():
        folder_id = await session.scalar(
            select(Folder.id).where(
                Folder.account_id == account_id,
                Folder.name == "INBOX",
            )
        )
        assert folder_id is not None
        session.add(
            SyncJob(
                account_id=account_id,
                folder_id=folder_id,
                batch_id=uuid4(),
                state=SyncJobState.FAILED.value,
                priority=0,
                attempts=1,
                last_error="ancient failure",
                created_at=datetime.now(UTC) - timedelta(hours=48),
            )
        )

    recent = (await client.get("/api/v1/metrics", params={"window_hours": 24})).json()
    assert recent["failures"] == 0

    wider = (await client.get("/api/v1/metrics", params={"window_hours": 72})).json()
    assert wider["failures"] == 1


async def test_metrics_report_outbox_backlog(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    await _seed_and_sync(client, account_payload, mock_server)

    messages = (await client.get("/api/v1/messages")).json()
    target = next(message for message in messages if message["subject"] == "One")

    patched = await client.patch(
        f"/api/v1/messages/{target['id']}",
        json={"is_read": True},
    )
    assert patched.status_code == 200

    body = (await client.get("/api/v1/metrics")).json()
    outbox = body["outbox"]

    # It is either still queued or already delivered, never lost.
    assert outbox["outstanding"] + outbox["success"] == 1
    assert outbox["failed"] == 0


async def test_metrics_require_an_account(client: AsyncClient) -> None:
    response = await client.get("/api/v1/metrics")
    assert response.status_code == 404


async def test_metrics_reject_an_absurd_window(client: AsyncClient) -> None:
    response = await client.get("/api/v1/metrics", params={"window_hours": 0})
    assert response.status_code == 422

"""Flag changes over the API: optimistic locally, durable on the way out."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.sync import SyncJob
from hymail_api.domain.enums import SyncJobState
from tests.api.helpers import message_bytes, wait_for_batch, wait_for_outbox_idle


class SyncFixture:
    account_id: UUID
    folder_id: UUID
    messages: list[dict[str, object]]


async def _configure_and_sync(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> SyncFixture:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201

    mock_server.add_message(message_bytes("One"), mailbox="INBOX", uid=1)

    refresh = await client.post("/api/v1/folders/refresh")
    assert refresh.status_code == 200

    trigger = await client.post("/api/v1/sync/trigger-all", json={})
    await wait_for_batch(client, trigger.json()["batch_id"])

    fixture = SyncFixture()
    fixture.account_id = UUID(
        (await client.get("/api/v1/accounts/current")).json()["id"]
    )
    folders = (await client.get("/api/v1/folders")).json()
    fixture.folder_id = UUID(
        next(f for f in folders if f["name"] == "INBOX")["id"]
    )
    fixture.messages = (await client.get("/api/v1/messages")).json()
    return fixture


async def _hold_the_account_busy(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    folder_id: UUID,
) -> None:
    """Keep a sync job running so the outbox worker cannot claim.

    This is the account mutex doing its job, and it is what makes the
    coalescing and discard tests deterministic instead of racing the worker.
    """
    async with session_factory() as session, session.begin():
        session.add(
            SyncJob(
                account_id=account_id,
                folder_id=folder_id,
                batch_id=uuid4(),
                state=SyncJobState.RUNNING.value,
                priority=0,
                lease_expires_at=datetime.now(UTC)
                + timedelta(seconds=300),
            )
        )


async def _release_the_account(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(SyncJob)
            .where(
                SyncJob.account_id == account_id,
                SyncJob.state == SyncJobState.RUNNING.value,
            )
            .values(state=SyncJobState.CANCELLED.value)
        )


async def test_marking_read_writes_through_to_the_server(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    fixture = await _configure_and_sync(client, account_payload, mock_server)
    target = fixture.messages[0]
    assert target["is_read"] is False

    patched = await client.patch(
        f"/api/v1/messages/{target['id']}",
        json={"is_read": True},
    )

    assert patched.status_code == 200
    # The response is already optimistic...
    assert patched.json()["is_read"] is True
    assert patched.json()["outbox_state"] == "pending"

    await wait_for_outbox_idle(client)

    # ...and the server eventually agrees.
    assert "\\Seen" in mock_server.folders["INBOX"][0].flags

    after = (await client.get("/api/v1/messages")).json()
    assert after[0]["is_read"] is True
    assert after[0]["outbox_state"] is None


async def test_star_and_read_are_tracked_independently(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    fixture = await _configure_and_sync(client, account_payload, mock_server)
    target = fixture.messages[0]

    await client.patch(
        f"/api/v1/messages/{target['id']}",
        json={"is_starred": True},
    )
    await wait_for_outbox_idle(client)

    assert mock_server.folders["INBOX"][0].flags == ["\\Flagged"]

    detail = (await client.get(f"/api/v1/messages/{target['id']}")).json()
    assert detail["is_starred"] is True
    assert detail["is_read"] is False


async def test_toggling_back_coalesces_into_one_queued_write(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Read then unread while queued must not become two contradictory writes."""
    fixture = await _configure_and_sync(client, account_payload, mock_server)
    target = fixture.messages[0]
    await _hold_the_account_busy(
        session_factory,
        fixture.account_id,
        fixture.folder_id,
    )

    for value in (True, False):
        response = await client.patch(
            f"/api/v1/messages/{target['id']}",
            json={"is_read": value},
        )
        assert response.status_code == 200

    queued = (
        await client.get("/api/v1/outbox", params={"active_only": True})
    ).json()
    assert len(queued) == 1
    assert queued[0]["value"] is False

    await _release_the_account(session_factory, fixture.account_id)
    await wait_for_outbox_idle(client)

    # The server ended up where the user left it, having heard one write.
    assert mock_server.folders["INBOX"][0].flags == []
    actions = (await client.get("/api/v1/outbox")).json()
    assert len(actions) == 1
    assert actions[0]["state"] == "success"


async def test_discard_restores_the_server_state(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fixture = await _configure_and_sync(client, account_payload, mock_server)
    target = fixture.messages[0]
    await _hold_the_account_busy(
        session_factory,
        fixture.account_id,
        fixture.folder_id,
    )

    await client.patch(
        f"/api/v1/messages/{target['id']}",
        json={"is_read": True},
    )

    queued = (
        await client.get("/api/v1/outbox", params={"active_only": True})
    ).json()
    assert len(queued) == 1

    discarded = await client.post(f"/api/v1/outbox/{queued[0]['id']}/discard")
    assert discarded.status_code == 200
    assert discarded.json() == {"updated": True}

    detail = (await client.get(f"/api/v1/messages/{target['id']}")).json()
    assert detail["is_read"] is False
    assert detail["outbox_state"] is None

    # Nothing was sent, and the write never becomes eligible.
    await _release_the_account(session_factory, fixture.account_id)
    await wait_for_outbox_idle(client)
    assert mock_server.folders["INBOX"][0].flags == []


async def test_retry_requeues_a_failed_action(
    client: AsyncClient,
    account_payload: dict[str, object],
    mock_server,
) -> None:
    fixture = await _configure_and_sync(client, account_payload, mock_server)
    target = fixture.messages[0]

    # Make the server refuse the write.
    mock_server.scenario.auth_failures = 99

    await client.patch(
        f"/api/v1/messages/{target['id']}",
        json={"is_read": True},
    )
    await wait_for_outbox_idle(client)

    actions = (await client.get("/api/v1/outbox")).json()
    assert actions[0]["state"] == "failed"

    # The account is paused, which the UI needs to be able to see.
    account = (await client.get("/api/v1/accounts/current")).json()
    assert account["status"] == "auth_expired"

    mock_server.scenario.auth_failures = 0
    retry = await client.post(f"/api/v1/outbox/{actions[0]['id']}/retry")
    assert retry.status_code == 200
    assert retry.json() == {"updated": True}

    await wait_for_outbox_idle(client)

    assert "\\Seen" in mock_server.folders["INBOX"][0].flags

"""Shared polling helpers for API tests."""

import asyncio
from email.mime.text import MIMEText

from httpx import AsyncClient


def message_bytes(subject: str, body: str = "body") -> bytes:
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    return message.as_bytes()


async def wait_for_batch(
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


async def wait_for_outbox_idle(
    client: AsyncClient,
    deadline_seconds: float = 10.0,
) -> None:
    """Block until no outbox action is pending or in flight."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    while loop.time() < deadline:
        response = await client.get(
            "/api/v1/outbox",
            params={"active_only": True},
        )
        assert response.status_code == 200
        if not response.json():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("outbox did not drain in time")

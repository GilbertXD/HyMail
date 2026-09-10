from httpx import AsyncClient


async def test_create_and_read_current_account(
    client: AsyncClient,
    account_payload: dict[str, object],
) -> None:
    create_response = await client.post("/api/v1/accounts", json=account_payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["email"] == "user@example.com"
    assert created["provider"] == "custom"
    assert "secret" not in created

    current_response = await client.get("/api/v1/accounts/current")
    assert current_response.status_code == 200
    assert current_response.json()["email"] == "user@example.com"


async def test_connection_test_endpoint(
    client: AsyncClient,
    account_payload: dict[str, object],
) -> None:
    response = await client.post("/api/v1/accounts/test", json=account_payload)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "connection ok"}
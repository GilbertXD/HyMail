from httpx import AsyncClient


async def test_openapi_contains_business_routes(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/accounts" in paths
    assert "/api/v1/accounts/current" in paths
    assert "/api/v1/folders" in paths
    assert "/api/v1/sync/trigger" in paths
from httpx import ASGITransport, AsyncClient

from hymail_api.main import create_app


async def test_health_public_and_api_requires_token(session_factory) -> None:
    app = create_app(
        session_factory=session_factory,
        imap_client_factory=lambda _account: None,
        api_token="secret",
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        health = await client.get("/health")
        assert health.status_code == 200

        unauthorized = await client.get("/api/v1/accounts/current")
        assert unauthorized.status_code == 401

        authorized = await client.get(
            "/api/v1/accounts/current",
            headers={"Authorization": "Bearer secret"},
        )
        assert authorized.status_code == 404


async def test_invalid_origin_is_rejected(session_factory) -> None:
    app = create_app(
        session_factory=session_factory,
        imap_client_factory=lambda _account: None,
        api_token="secret",
        allowed_origins=["http://127.0.0.1:5173"],
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/accounts/current",
            headers={
                "Authorization": "Bearer secret",
                "Origin": "http://evil.example",
            },
        )
        assert response.status_code == 403


async def test_allowed_origin_passes(session_factory) -> None:
    app = create_app(
        session_factory=session_factory,
        imap_client_factory=lambda _account: None,
        api_token="secret",
        allowed_origins=["http://127.0.0.1:5173"],
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/health",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert response.status_code == 200
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.main import create_app

ORIGIN = "http://127.0.0.1:5173"


async def test_unhandled_error_keeps_cors_headers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A crashing endpoint must still produce a readable response.

    Starlette's ServerErrorMiddleware lives outside CORSMiddleware, so an
    unhandled exception used to go out with no CORS headers and surface in the
    browser as "Failed to fetch" instead of a 500.
    """
    app = create_app(session_factory=session_factory)

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": ORIGIN},
    ) as client:
        response = await client.get("/api/v1/boom")

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert response.json() == {"detail": "internal server error"}

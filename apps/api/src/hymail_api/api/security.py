from collections.abc import Sequence
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)

DEFAULT_ALLOWED_HOSTS = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "::1",
        "test",
        "testserver",
    }
)


class LocalApiSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        api_token: str | None = None,
        allowed_origins: Sequence[str] | None = None,
        allowed_hosts: Sequence[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.api_token = api_token
        self.allowed_origins = frozenset(
            allowed_origins or DEFAULT_ALLOWED_ORIGINS
        )
        self.allowed_hosts = frozenset(
            allowed_hosts or DEFAULT_ALLOWED_HOSTS
        )

    async def dispatch(self, request: Request, call_next):
        host = urlsplit(
            f"//{request.headers.get('host', '')}"
        ).hostname
        if host is None or host.lower() not in self.allowed_hosts:
            return JSONResponse(
                {"detail": "invalid host"},
                status_code=400,
            )

        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            return JSONResponse(
                {"detail": "invalid origin"},
                status_code=403,
            )

        if (
            request.method != "OPTIONS"
            and self.api_token
            and request.url.path.startswith("/api/")
        ):
            authorization = request.headers.get("authorization", "")
            if authorization != f"Bearer {self.api_token}":
                return JSONResponse(
                    {"detail": "unauthorized"},
                    status_code=401,
                )

        return await call_next(request)
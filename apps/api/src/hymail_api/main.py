from collections.abc import Callable, Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.api.router import api_router
from hymail_api.api.security import (
    DEFAULT_ALLOWED_ORIGINS,
    LocalApiSecurityMiddleware,
)
from hymail_api.core.config import settings
from hymail_api.db.models.account import Account
from hymail_api.db.session import SessionLocal
from hymail_api.imap.client import ImapClient
from hymail_api.services.accounts import build_imap_client
from hymail_api.services.sync_manager import SyncManager


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    imap_client_factory: Callable[[Account], ImapClient] = build_imap_client,
    api_token: str | None = None,
    allowed_origins: Sequence[str] | None = None,
) -> FastAPI:
    effective_token = settings.api_token if api_token is None else api_token
    origins = list(allowed_origins or DEFAULT_ALLOWED_ORIGINS)

    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs",
        redoc_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(
        LocalApiSecurityMiddleware,
        api_token=effective_token,
        allowed_origins=origins,
    )
    application.state.session_factory = session_factory
    application.state.sync_manager = SyncManager(
        session_factory=session_factory,
        client_factory=imap_client_factory,
    )
    application.include_router(api_router)

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "hymail-api",
            "version": settings.version,
        }

    return application


app = create_app()
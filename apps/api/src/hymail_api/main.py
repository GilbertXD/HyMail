from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.api.router import api_router
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
) -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs",
        redoc_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
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
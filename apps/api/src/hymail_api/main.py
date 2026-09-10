from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.api.errors import UnhandledErrorMiddleware
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
from hymail_api.services.outbox import OutboxDispatcher
from hymail_api.services.sync_scheduler import SyncScheduler


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    imap_client_factory: Callable[[Account], ImapClient] = build_imap_client,
    api_token: str | None = None,
    allowed_origins: Sequence[str] | None = None,
    scheduler: SyncScheduler | None = None,
    outbox_dispatcher: OutboxDispatcher | None = None,
) -> FastAPI:
    effective_token = settings.api_token if api_token is None else api_token
    origins = list(allowed_origins or DEFAULT_ALLOWED_ORIGINS)

    sync_scheduler = scheduler or SyncScheduler(
        session_factory=session_factory,
        client_factory=imap_client_factory,
    )
    outbox = outbox_dispatcher or OutboxDispatcher(
        session_factory=session_factory,
        client_factory=imap_client_factory,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Re-queues whatever a previous process left running before serving.
        await sync_scheduler.ensure_started()
        await outbox.ensure_started()
        try:
            yield
        finally:
            await outbox.stop()
            await sync_scheduler.stop()

    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    # Middleware added last runs first. The error handler must sit *inside*
    # CORSMiddleware so its 500 response still gets CORS headers.
    application.add_middleware(UnhandledErrorMiddleware)
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
    application.state.sync_scheduler = sync_scheduler
    application.state.outbox_dispatcher = outbox
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

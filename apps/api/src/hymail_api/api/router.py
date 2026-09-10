from fastapi import APIRouter

from hymail_api.api.routes import accounts, folders, messages, outbox, sync

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(folders.router, prefix="/folders", tags=["folders"])
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(outbox.router, prefix="/outbox", tags=["outbox"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
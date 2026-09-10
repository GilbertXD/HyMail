from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.services.sync_scheduler import SyncScheduler


def get_session_factory(
    request: Request,
) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(request)
    async with factory() as session:
        yield session


def get_sync_scheduler(request: Request) -> SyncScheduler:
    return request.app.state.sync_scheduler


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SchedulerDep = Annotated[SyncScheduler, Depends(get_sync_scheduler)]

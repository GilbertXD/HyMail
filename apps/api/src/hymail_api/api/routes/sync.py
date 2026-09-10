from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hymail_api.api.deps import ManagerDep, SessionDep
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.sync import SyncCursor, SyncEvent
from hymail_api.schemas.sync import (
    SyncCancelRequest,
    SyncCancelResponse,
    SyncEventRead,
    SyncStatusRead,
    SyncTriggerRequest,
)
from hymail_api.services import accounts
from hymail_api.services.sync_manager import SyncManager

router = APIRouter()


@router.post("/trigger", response_model=SyncStatusRead, status_code=202)
async def trigger_sync(
    payload: SyncTriggerRequest,
    session: SessionDep,
    manager: ManagerDep,
) -> SyncStatusRead:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    await manager.start(account.id, payload.folder)
    return await _build_status(session, manager, account.id, payload.folder)


@router.post("/cancel", response_model=SyncCancelResponse)
async def cancel_sync(
    payload: SyncCancelRequest,
    session: SessionDep,
    manager: ManagerDep,
) -> SyncCancelResponse:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    cancelled = await manager.cancel(account.id, payload.folder)
    return SyncCancelResponse(cancelled=cancelled)


@router.get("/status", response_model=SyncStatusRead)
async def get_sync_status(
    session: SessionDep,
    manager: ManagerDep,
    folder: Annotated[str, Query()] = "INBOX",
) -> SyncStatusRead:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")
    return await _build_status(session, manager, account.id, folder)


@router.get("/events", response_model=list[SyncEventRead])
async def list_sync_events(
    session: SessionDep,
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SyncEventRead]:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    result = await session.scalars(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == account.id,
            SyncEvent.id > after_id,
        )
        .order_by(SyncEvent.id)
        .limit(limit)
    )
    return list(result)


async def _build_status(
    session: AsyncSession,
    manager: SyncManager,
    account_id: UUID,
    folder_name: str,
) -> SyncStatusRead:
    folder = await session.scalar(
        select(Folder).where(
            Folder.account_id == account_id,
            Folder.name == folder_name,
        )
    )
    cursor = None
    if folder is not None:
        cursor = await session.scalar(
            select(SyncCursor).where(
                SyncCursor.account_id == account_id,
                SyncCursor.folder_id == folder.id,
            )
        )

    task_status = manager.get_status(account_id, folder_name)
    running = task_status.running if task_status is not None else False
    if task_status is not None and task_status.state != "idle":
        state = task_status.state
    elif cursor is not None:
        state = cursor.state
    else:
        state = "idle"

    return SyncStatusRead(
        account_id=account_id,
        folder=folder_name,
        running=running,
        state=state,
        last_uid=cursor.last_uid if cursor is not None else 0,
        uidvalidity=cursor.uidvalidity if cursor is not None else None,
        uidnext=cursor.uidnext if cursor is not None else None,
        attempts=cursor.attempts if cursor is not None else 0,
        last_error=(
            task_status.error
            if task_status is not None and task_status.error
            else (cursor.last_error if cursor is not None else None)
        ),
        trace_id=task_status.trace_id if task_status is not None else None,
        last_sync_at=(
            cursor.last_sync_at if cursor is not None else None
        ),
    )
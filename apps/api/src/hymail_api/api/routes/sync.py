from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hymail_api.api.deps import SchedulerDep, SessionDep
from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.sync import SyncCursor, SyncEvent, SyncJob
from hymail_api.domain.enums import SyncJobKind, SyncPriority
from hymail_api.imap.errors import ImapError
from hymail_api.schemas.sync import (
    SyncBatchRead,
    SyncCancelRequest,
    SyncCancelResponse,
    SyncEventRead,
    SyncJobRead,
    SyncStatusRead,
    SyncTriggerAllRequest,
    SyncTriggerRequest,
    SyncTriggerResponse,
)
from hymail_api.services import accounts
from hymail_api.services.sync_scheduler import AccountPausedError

router = APIRouter()

_ACTIVE_JOB_STATES = ("queued", "running")
_SKIP_FOLDER_FLAGS = {"\\NOSELECT", "\\NONEXISTENT"}


@router.post("/trigger", response_model=SyncTriggerResponse, status_code=202)
async def trigger_sync(
    payload: SyncTriggerRequest,
    session: SessionDep,
    scheduler: SchedulerDep,
) -> SyncTriggerResponse:
    account = await _require_account(session)
    folder = await _require_folder(session, account.id, payload.folder)

    try:
        job = await scheduler.enqueue_folder(account.id, folder.id)
    except AccountPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SyncTriggerResponse(
        batch_id=job.batch_id,
        job_ids=[job.id],
        queued=1,
    )


@router.post("/trigger-all", response_model=SyncTriggerResponse, status_code=202)
async def trigger_all_sync(
    payload: SyncTriggerAllRequest,
    session: SessionDep,
    scheduler: SchedulerDep,
) -> SyncTriggerResponse:
    """Queue every folder that still exists on the server.

    Local folders left over from a previously configured mailbox are skipped:
    the server would answer every one of them with "mailbox not found".
    """
    account = await _require_account(session)
    targets, skipped = await _select_targets(
        session,
        account,
        payload.folder_names,
    )

    batch_id = uuid4()
    try:
        jobs = await scheduler.enqueue_folders(
            account.id,
            [folder.id for folder in targets],
            batch_id=batch_id,
        )
    except AccountPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SyncTriggerResponse(
        batch_id=batch_id,
        job_ids=[job.id for job in jobs],
        queued=len(jobs),
        skipped=skipped + (len(targets) - len(jobs)),
    )


@router.post("/reconcile", response_model=SyncTriggerResponse, status_code=202)
async def trigger_reconcile(
    payload: SyncTriggerAllRequest,
    session: SessionDep,
    scheduler: SchedulerDep,
) -> SyncTriggerResponse:
    """Queue a reconcile pass.

    Each job pulls new mail first and then compares the server UID set against
    the local one, flagging messages that are no longer there.
    """
    account = await _require_account(session)
    targets, skipped = await _select_targets(
        session,
        account,
        payload.folder_names,
    )

    batch_id = uuid4()
    try:
        jobs = await scheduler.enqueue_folders(
            account.id,
            [folder.id for folder in targets],
            batch_id=batch_id,
            kind=SyncJobKind.RECONCILE,
            priority=SyncPriority.RECONCILE,
        )
    except AccountPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SyncTriggerResponse(
        batch_id=batch_id,
        job_ids=[job.id for job in jobs],
        queued=len(jobs),
        skipped=skipped + (len(targets) - len(jobs)),
    )


@router.post("/cancel", response_model=SyncCancelResponse)
async def cancel_sync(
    payload: SyncCancelRequest,
    session: SessionDep,
    scheduler: SchedulerDep,
) -> SyncCancelResponse:
    account = await _require_account(session)
    cancelled = 0

    if payload.batch_id is not None:
        cancelled += await scheduler.cancel_batch(payload.batch_id)

    if payload.folder is not None:
        folder = await _find_folder(session, account.id, payload.folder)
        if folder is not None:
            cancelled += await scheduler.cancel_folder(account.id, folder.id)

    return SyncCancelResponse(cancelled=cancelled)


@router.get("/batches/{batch_id}", response_model=SyncBatchRead)
async def get_batch(
    batch_id: UUID,
    scheduler: SchedulerDep,
) -> SyncBatchRead:
    summary = await scheduler.batch_summary(batch_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="batch not found")

    return SyncBatchRead(
        batch_id=summary.batch_id,
        total=summary.total,
        queued=summary.queued,
        running=summary.running,
        success=summary.success,
        failed=summary.failed,
        cancelled=summary.cancelled,
        state=summary.state.value,
        current_folder=summary.current_folder,
        last_error=summary.last_error,
    )


@router.get("/jobs", response_model=list[SyncJobRead])
async def list_sync_jobs(
    session: SessionDep,
    scheduler: SchedulerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SyncJobRead]:
    account = await _require_account(session)
    rows = await scheduler.list_jobs(account.id, limit=limit)

    return [
        SyncJobRead(
            id=job.id,
            folder_id=job.folder_id,
            folder_name=folder_name,
            batch_id=job.batch_id,
            kind=job.kind,
            state=job.state,
            priority=job.priority,
            attempts=job.attempts,
            last_error=job.last_error,
            not_before=job.not_before,
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
        )
        for job, folder_name in rows
    ]


@router.get("/status", response_model=SyncStatusRead)
async def get_sync_status(
    session: SessionDep,
    folder: Annotated[str, Query()] = "INBOX",
) -> SyncStatusRead:
    account = await _require_account(session)
    return await _build_status(session, account.id, folder)


@router.get("/events", response_model=list[SyncEventRead])
async def list_sync_events(
    session: SessionDep,
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SyncEventRead]:
    account = await _require_account(session)

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


async def _require_account(session: AsyncSession) -> Account:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")
    return account


async def _find_folder(
    session: AsyncSession,
    account_id: UUID,
    folder_name: str,
) -> Folder | None:
    return await session.scalar(
        select(Folder).where(
            Folder.account_id == account_id,
            Folder.name == folder_name,
        )
    )


async def _require_folder(
    session: AsyncSession,
    account_id: UUID,
    folder_name: str,
) -> Folder:
    folder = await _find_folder(session, account_id, folder_name)
    if folder is None:
        raise HTTPException(
            status_code=404,
            detail=f"folder not found: {folder_name}",
        )
    return folder


async def _select_targets(
    session: AsyncSession,
    account: Account,
    folder_names: list[str] | None,
) -> tuple[list[Folder], int]:
    """Local folders that still exist on the server, plus how many were dropped."""
    folders = list(
        await session.scalars(
            select(Folder)
            .where(Folder.account_id == account.id)
            .order_by(Folder.name)
        )
    )
    if not folders:
        raise HTTPException(
            status_code=400,
            detail="no folders known locally; refresh folders first",
        )

    wanted = [
        folder
        for folder in folders
        if not folder_names or folder.name in folder_names
    ]
    remote_names = await _remote_folder_names(account)
    targets = [folder for folder in wanted if folder.name in remote_names]
    return targets, len(wanted) - len(targets)


async def _remote_folder_names(account: Account) -> set[str]:
    client = accounts.build_imap_client(account)
    try:
        await client.connect()
        remote_folders = await client.list_folders()
    except ImapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await client.close()

    return {
        folder.name
        for folder in remote_folders
        if not any(
            flag.upper() in _SKIP_FOLDER_FLAGS for flag in folder.flags
        )
    }


async def _build_status(
    session: AsyncSession,
    account_id: UUID,
    folder_name: str,
) -> SyncStatusRead:
    folder = await _find_folder(session, account_id, folder_name)

    cursor = None
    running = False
    job_error: str | None = None
    if folder is not None:
        cursor = await session.scalar(
            select(SyncCursor).where(
                SyncCursor.account_id == account_id,
                SyncCursor.folder_id == folder.id,
            )
        )
        job = await session.scalar(
            select(SyncJob)
            .where(
                SyncJob.account_id == account_id,
                SyncJob.folder_id == folder.id,
            )
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        )
        if job is not None:
            running = job.state in _ACTIVE_JOB_STATES
            job_error = job.last_error

    trace_id = None
    if folder is not None:
        trace_id = await session.scalar(
            select(SyncEvent.trace_id)
            .where(
                SyncEvent.account_id == account_id,
                SyncEvent.folder_id == folder.id,
            )
            .order_by(SyncEvent.id.desc())
            .limit(1)
        )

    return SyncStatusRead(
        account_id=account_id,
        folder=folder_name,
        running=running,
        state=cursor.state if cursor is not None else "idle",
        last_uid=cursor.last_uid if cursor is not None else 0,
        uidvalidity=cursor.uidvalidity if cursor is not None else None,
        uidnext=cursor.uidnext if cursor is not None else None,
        attempts=cursor.attempts if cursor is not None else 0,
        last_error=(
            job_error
            if job_error is not None
            else (cursor.last_error if cursor is not None else None)
        ),
        trace_id=trace_id,
        last_sync_at=cursor.last_sync_at if cursor is not None else None,
    )

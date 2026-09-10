from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from hymail_api.api.deps import SessionDep
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.schemas.folder import FolderRead
from hymail_api.schemas.message import MessageSummary
from hymail_api.services import accounts

router = APIRouter()


@router.get("", response_model=list[FolderRead])
async def list_folders(session: SessionDep) -> list[FolderRead]:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    result = await session.scalars(
        select(Folder)
        .where(Folder.account_id == account.id)
        .order_by(Folder.name)
    )
    return list(result)


@router.get("/{folder_id}/messages", response_model=list[MessageSummary])
async def list_messages(
    folder_id: UUID,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageSummary]:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    folder = await session.scalar(
        select(Folder).where(
            Folder.id == folder_id,
            Folder.account_id == account.id,
        )
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="folder not found")

    result = await session.scalars(
        select(Message)
        .where(Message.folder_id == folder.id)
        .order_by(Message.uid.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        MessageSummary(
            id=message.id,
            folder_id=message.folder_id,
            uid=message.uid,
            subject=message.subject,
            from_name=message.from_name,
            from_addr=message.from_addr,
            date=message.date,
            size=message.size,
            flags=message.flags_json,
        )
        for message in result
    ]
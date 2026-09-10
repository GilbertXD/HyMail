from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from hymail_api.api.deps import SessionDep
from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.schemas.message import MessageDetail, MessageSummary
from hymail_api.services import accounts

router = APIRouter()


@router.get("", response_model=list[MessageSummary])
async def list_all_messages(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageSummary]:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    rows = (
        await session.execute(
            select(Message, Folder.name, Account.email)
            .join(Folder, Folder.id == Message.folder_id)
            .join(Account, Account.id == Message.account_id)
            .where(Message.account_id == account.id)
            .order_by(Message.date.desc(), Message.uid.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

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
            folder_name=folder_name,
            account_email=email,
            remote_missing=message.remote_missing,
        )
        for message, folder_name, email in rows
    ]


@router.get("/{message_id}", response_model=MessageDetail)
async def get_message(
    message_id: UUID,
    session: SessionDep,
) -> MessageDetail:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    message = await session.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.account_id == account.id,
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")

    return MessageDetail(
        id=message.id,
        folder_id=message.folder_id,
        uid=message.uid,
        subject=message.subject,
        from_name=message.from_name,
        from_addr=message.from_addr,
        date=message.date,
        size=message.size,
        flags=message.flags_json,
        to=message.to_json,
        cc=message.cc_json,
        raw_headers=message.raw_headers,
        body_text=message.body_text,
        body_html=message.body_html,
        remote_missing=message.remote_missing,
    )
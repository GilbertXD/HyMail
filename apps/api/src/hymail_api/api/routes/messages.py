from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from hymail_api.api.deps import SessionDep
from hymail_api.db.models.message import Message
from hymail_api.schemas.message import MessageDetail
from hymail_api.services import accounts

router = APIRouter()


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
    )
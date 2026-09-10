from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hymail_api.api.deps import OutboxDep, SessionDep
from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.domain.enums import OutboxActionType
from hymail_api.schemas.message import (
    MessageDetail,
    MessageFlagUpdate,
    MessageSummary,
)
from hymail_api.services import accounts

router = APIRouter()


async def _require_account(session: AsyncSession) -> Account:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")
    return account


async def _moved_to_name(
    session: AsyncSession,
    message: Message,
) -> str | None:
    if message.moved_to_folder_id is None:
        return None
    return await session.scalar(
        select(Folder.name).where(Folder.id == message.moved_to_folder_id)
    )


async def _detail(
    session: AsyncSession,
    message: Message,
    outbox_state: str | None = None,
) -> MessageDetail:
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
        moved_to_folder_name=await _moved_to_name(session, message),
        is_read=message.is_read,
        is_starred=message.is_starred,
        outbox_state=outbox_state,
    )


@router.get("", response_model=list[MessageSummary])
async def list_all_messages(
    session: SessionDep,
    outbox: OutboxDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageSummary]:
    account = await _require_account(session)
    pending = await outbox.pending_message_ids(account.id)

    destination = aliased(Folder)
    rows = (
        await session.execute(
            select(Message, Folder.name, Account.email, destination.name)
            .join(Folder, Folder.id == Message.folder_id)
            .join(Account, Account.id == Message.account_id)
            .outerjoin(
                destination,
                destination.id == Message.moved_to_folder_id,
            )
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
            moved_to_folder_name=moved_to,
            is_read=message.is_read,
            is_starred=message.is_starred,
            outbox_state=pending.get(message.id),
        )
        for message, folder_name, email, moved_to in rows
    ]


@router.get("/{message_id}", response_model=MessageDetail)
async def get_message(
    message_id: UUID,
    session: SessionDep,
    outbox: OutboxDep,
) -> MessageDetail:
    account = await _require_account(session)
    message = await _require_message(session, account.id, message_id)
    pending = await outbox.pending_message_ids(account.id)
    return await _detail(session, message, pending.get(message.id))


@router.patch("/{message_id}", response_model=MessageDetail)
async def update_message_flags(
    message_id: UUID,
    payload: MessageFlagUpdate,
    session: SessionDep,
    outbox: OutboxDep,
) -> MessageDetail:
    """Change read/starred locally and queue the write to the server.

    The local row and the queued intent commit in one transaction: a crash
    must not leave the interface claiming something the server was never told.
    """
    account = await _require_account(session)
    message = await _require_message(session, account.id, message_id)

    # The lookups above already opened a transaction, so this commits it
    # rather than starting a second one: the local row and the queued intent
    # land together.
    for action_type, desired, current in (
        (OutboxActionType.MARK_READ, payload.is_read, message.is_read),
        (OutboxActionType.STAR, payload.is_starred, message.is_starred),
    ):
        if desired is None or desired == current:
            continue
        if action_type is OutboxActionType.MARK_READ:
            message.is_read = desired
        else:
            message.is_starred = desired
        await outbox.enqueue_flag_change(
            account_id=account.id,
            message_id=message.id,
            folder_id=message.folder_id,
            uid=message.uid,
            action_type=action_type,
            value=desired,
            session=session,
        )

    await session.commit()
    await outbox.notify()

    pending = await outbox.pending_message_ids(account.id)
    return await _detail(session, message, pending.get(message.id))


async def _require_message(
    session: AsyncSession,
    account_id: UUID,
    message_id: UUID,
) -> Message:
    message = await session.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.account_id == account_id,
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    return message
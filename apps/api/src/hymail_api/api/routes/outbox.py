from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from hymail_api.api.deps import OutboxDep, SessionDep
from hymail_api.db.models.account import Account
from hymail_api.schemas.outbox import OutboxActionRead, OutboxMutationResponse
from hymail_api.services import accounts

router = APIRouter()


@router.get("", response_model=list[OutboxActionRead])
async def list_outbox(
    session: SessionDep,
    outbox: OutboxDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    active_only: bool = False,
) -> list[OutboxActionRead]:
    account = await _require_account(session)
    rows = await outbox.list_actions(
        account.id,
        limit=limit,
        active_only=active_only,
    )

    return [
        OutboxActionRead(
            id=action.id,
            message_id=action.message_id,
            folder_id=action.folder_id,
            folder_name=folder_name,
            uid=action.uid,
            type=action.type,
            state=action.state,
            value=bool(action.payload_json.get("value", True)),
            attempts=action.attempts,
            last_error=action.last_error,
            next_retry_at=action.next_retry_at,
            created_at=action.created_at,
            subject=subject,
        )
        for action, subject, folder_name in rows
    ]


@router.post("/{action_id}/retry", response_model=OutboxMutationResponse)
async def retry_action(
    action_id: UUID,
    session: SessionDep,
    outbox: OutboxDep,
) -> OutboxMutationResponse:
    """Put a failed change back in the queue."""
    account = await _require_account(session)
    return OutboxMutationResponse(
        updated=await outbox.retry(action_id, account_id=account.id)
    )


@router.post("/{action_id}/discard", response_model=OutboxMutationResponse)
async def discard_action(
    action_id: UUID,
    session: SessionDep,
    outbox: OutboxDep,
) -> OutboxMutationResponse:
    """Drop a change and restore the local row to the server's state."""
    account = await _require_account(session)
    return OutboxMutationResponse(
        updated=await outbox.discard(action_id, account_id=account.id)
    )


async def _require_account(session: AsyncSession) -> Account:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")
    return account

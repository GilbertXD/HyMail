from fastapi import APIRouter, HTTPException, status

from hymail_api.api.deps import SessionDep
from hymail_api.imap.errors import ImapError
from hymail_api.schemas.account import (
    AccountCreate,
    AccountRead,
    ConnectionTestRequest,
    ConnectionTestResponse,
)
from hymail_api.services import accounts

router = APIRouter()


@router.get("/current", response_model=AccountRead)
async def read_current_account(session: SessionDep) -> AccountRead:
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="account not configured",
        )
    return account


@router.post("", response_model=AccountRead, status_code=201)
async def upsert_account(
    payload: AccountCreate,
    session: SessionDep,
) -> AccountRead:
    try:
        return await accounts.upsert_account(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test", response_model=ConnectionTestResponse)
async def test_connection(
    payload: ConnectionTestRequest,
) -> ConnectionTestResponse:
    try:
        await accounts.test_connection(payload)
    except (ImapError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConnectionTestResponse(ok=True, message="connection ok")
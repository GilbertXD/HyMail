from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hymail_api.db.models.account import Account
from hymail_api.imap.client import ImapClient
from hymail_api.imap.presets import get_preset
from hymail_api.schemas.account import AccountCreate, ConnectionTestRequest
from hymail_api.security.dpapi import protect_secret, unprotect_secret


async def get_current_account(session: AsyncSession) -> Account | None:
    return await session.scalar(
        select(Account).order_by(Account.created_at).limit(1)
    )


async def upsert_account(
    session: AsyncSession,
    payload: AccountCreate,
) -> Account:
    account = await get_current_account(session)
    host, port, ssl = _resolve_connection(payload)

    if account is None:
        account = Account(email=payload.email)
        session.add(account)

    account.email = payload.email
    account.display_name = payload.display_name
    account.provider = payload.provider
    account.imap_host = host
    account.imap_port = port
    account.imap_ssl = ssl
    account.username = payload.username or payload.email
    account.secret_encrypted = protect_secret(payload.secret)
    account.status = "active"

    await session.commit()
    await session.refresh(account)
    return account


async def test_connection(payload: ConnectionTestRequest) -> None:
    host, port, ssl = _resolve_connection(payload)
    client = ImapClient(
        host=host,
        port=port,
        ssl=ssl,
        username=payload.username or payload.email,
        password=payload.secret,
        timeout=10.0,
    )
    try:
        await client.connect()
        await client.list_folders()
    finally:
        await client.close()


def build_imap_client(account: Account) -> ImapClient:
    if not account.imap_host:
        raise ValueError(f"account {account.email} has no IMAP host")
    secret = (
        unprotect_secret(account.secret_encrypted)
        if account.secret_encrypted
        else ""
    )
    return ImapClient(
        host=account.imap_host,
        port=account.imap_port or 993,
        ssl=account.imap_ssl,
        username=account.username or account.email,
        password=secret,
        client_id={"name": "HyMail", "version": "0.0.1"},
    )


def _resolve_connection(
    payload: AccountCreate | ConnectionTestRequest,
) -> tuple[str, int, bool]:
    provider = payload.provider.lower()
    if provider in {"163", "qq"}:
        preset = get_preset(provider)
        return (
            payload.imap_host or preset.host,
            payload.imap_port or preset.port,
            payload.imap_ssl,
        )
    if not payload.imap_host:
        raise ValueError("imap_host is required for custom provider")
    return payload.imap_host, payload.imap_port or 993, payload.imap_ssl
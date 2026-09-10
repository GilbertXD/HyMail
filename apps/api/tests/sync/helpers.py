from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.db.models.sync import SyncCursor, SyncEvent


async def get_cursor_values(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    folder_name: str,
) -> tuple | None:
    async with session_factory() as session:
        row = (
            await session.execute(
                select(
                    SyncCursor.state,
                    SyncCursor.last_uid,
                    SyncCursor.uidvalidity,
                    SyncCursor.uidnext,
                    SyncCursor.attempts,
                    SyncCursor.last_error,
                )
                .join(Folder, Folder.id == SyncCursor.folder_id)
                .where(
                    SyncCursor.account_id == account_id,
                    Folder.name == folder_name,
                )
            )
        ).one_or_none()
        return tuple(row) if row is not None else None


async def get_message_subjects(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    folder_name: str,
) -> list[str]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Message.subject)
                .join(Folder, Folder.id == Message.folder_id)
                .where(
                    Message.account_id == account_id,
                    Folder.name == folder_name,
                )
                .order_by(Message.uid)
            )
        ).all()
        return [row[0] for row in rows]


async def count_messages(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    folder_name: str,
) -> int:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Message)
            .join(Folder, Folder.id == Message.folder_id)
            .where(
                Message.account_id == account_id,
                Folder.name == folder_name,
            )
        )
        return int(count or 0)


async def get_event_values(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> list[tuple]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    SyncEvent.event_type,
                    SyncEvent.state,
                    SyncEvent.uid_from,
                    SyncEvent.uid_to,
                    SyncEvent.fetched_count,
                )
                .where(SyncEvent.account_id == account_id)
                .order_by(SyncEvent.id)
            )
        ).all()
        return [tuple(row) for row in rows]


async def get_account_status(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> str | None:
    async with session_factory() as session:
        return await session.scalar(
            select(Account.status).where(Account.id == account_id)
        )
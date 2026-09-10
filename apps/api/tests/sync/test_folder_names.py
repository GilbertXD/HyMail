"""Healing of folder rows written before the modified UTF-7 codec existed."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.imap.dto import RemoteFolder
from hymail_api.sync.store import get_or_create_folder, normalize_folder_names


async def _add_folder(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    name: str,
) -> UUID:
    async with session_factory() as session, session.begin():
        folder = Folder(account_id=account_id, name=name)
        session.add(folder)
        await session.flush()
        return folder.id


async def _folder_names(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> list[str]:
    async with session_factory() as session:
        names = await session.scalars(
            select(Folder.name).where(Folder.account_id == account_id)
        )
        return sorted(names)


async def test_normalize_renames_legacy_encoded_rows(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    folder_id = await _add_folder(session_factory, account_id, "&XfJSIJZk-")

    async with session_factory() as session, session.begin():
        renamed = await normalize_folder_names(session, account_id)

    assert renamed == 1
    assert await _folder_names(session_factory, account_id) == ["已删除"]

    # The row itself is kept, so message and cursor references stay valid.
    async with session_factory() as session:
        folder = await session.get(Folder, folder_id)
        assert folder is not None
        assert folder.name == "已删除"


async def test_normalize_keeps_messages_attached(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    folder_id = await _add_folder(session_factory, account_id, "&g0l6P3ux-")

    async with session_factory() as session, session.begin():
        session.add(
            Message(
                account_id=account_id,
                folder_id=folder_id,
                uid=7,
                subject="draft",
            )
        )

    async with session_factory() as session, session.begin():
        await normalize_folder_names(session, account_id)

    async with session_factory() as session:
        message = await session.scalar(
            select(Message).where(Message.folder_id == folder_id)
        )
        assert message is not None
        assert message.subject == "draft"


async def test_normalize_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    await _add_folder(session_factory, account_id, "&XfJSIJZk-")

    async with session_factory() as session, session.begin():
        assert await normalize_folder_names(session, account_id) == 1
    async with session_factory() as session, session.begin():
        assert await normalize_folder_names(session, account_id) == 0

    assert await _folder_names(session_factory, account_id) == ["已删除"]


async def test_normalize_leaves_colliding_rows_alone(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    await _add_folder(session_factory, account_id, "&XfJSIJZk-")
    await _add_folder(session_factory, account_id, "已删除")

    async with session_factory() as session, session.begin():
        renamed = await normalize_folder_names(session, account_id)

    assert renamed == 0
    assert await _folder_names(session_factory, account_id) == [
        "&XfJSIJZk-",
        "已删除",
    ]


async def test_normalize_ignores_already_plain_names(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    await _add_folder(session_factory, account_id, "INBOX")
    await _add_folder(session_factory, account_id, "Sent Messages")

    async with session_factory() as session, session.begin():
        renamed = await normalize_folder_names(session, account_id)

    assert renamed == 0
    assert await _folder_names(session_factory, account_id) == [
        "INBOX",
        "Sent Messages",
    ]


async def test_normalize_then_lookup_reuses_the_renamed_row(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    """The rename must be visible to a lookup in the same session.

    The app session runs with ``autoflush=False``, so without an explicit
    flush ``get_or_create_folder`` reads the stale name, misses the row and
    inserts a duplicate — which then collides with the pending rename on the
    ``(account_id, name)`` unique constraint.
    """
    await _add_folder(
        session_factory,
        account_id,
        "&UXZO1mWHTvZZOQ-/QQ&kK5O9ouilgU-",
    )

    async with session_factory() as session, session.begin():
        await normalize_folder_names(session, account_id)
        folder = await get_or_create_folder(
            session,
            account_id,
            RemoteFolder(
                name="其他文件夹/QQ邮件订阅",
                delimiter="/",
                flags=frozenset(),
            ),
        )
        assert folder.name == "其他文件夹/QQ邮件订阅"

    assert await _folder_names(session_factory, account_id) == [
        "其他文件夹/QQ邮件订阅"
    ]


async def test_normalize_then_lookup_with_autoflush_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    """Same as above, for several folders renamed in one pass."""
    legacy = {
        "&g0l6P3ux-": "草稿箱",
        "&XfJT0ZAB-": "已发送",
        "&i6KWBZCuTvY-": "订阅邮件",
    }
    for raw in legacy:
        await _add_folder(session_factory, account_id, raw)

    async with session_factory() as session, session.begin():
        renamed = await normalize_folder_names(session, account_id)
        assert renamed == len(legacy)
        for name in legacy.values():
            folder = await get_or_create_folder(
                session,
                account_id,
                RemoteFolder(name=name, delimiter="/", flags=frozenset()),
            )
            assert folder.name == name

    assert await _folder_names(session_factory, account_id) == sorted(
        legacy.values()
    )

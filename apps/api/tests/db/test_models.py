import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.base import Base
from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.db.models.sync import SyncCursor, SyncEvent
from hymail_api.db.session import create_engine


@pytest_asyncio.fixture
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    db_path = tmp_path / "models-test.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    engine = create_engine(database_url)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as db_session:
        yield db_session

    await engine.dispose()


async def test_sqlite_pragmas_are_enabled(session: AsyncSession) -> None:
    journal_mode = await session.scalar(text("PRAGMA journal_mode"))
    foreign_keys = await session.scalar(text("PRAGMA foreign_keys"))

    assert str(journal_mode).lower() == "wal"
    assert foreign_keys == 1


async def test_models_roundtrip(session: AsyncSession) -> None:
    account = Account(
        email="demo@example.com",
        provider="163",
        imap_host="imap.163.com",
        imap_port=993,
        imap_ssl=True,
        username="demo@example.com",
        status="active",
    )
    session.add(account)
    await session.flush()

    folder = Folder(
        account_id=account.id,
        name="INBOX",
        delimiter="/",
        uidvalidity=1,
        uidnext=101,
    )
    session.add(folder)
    await session.flush()

    message = Message(
        account_id=account.id,
        folder_id=folder.id,
        uid=1,
        message_id="<demo@example.com>",
        subject="Hello",
        from_addr="sender@example.com",
        to_json=["demo@example.com"],
        cc_json=[],
        flags_json=["\\Seen"],
        body_text="hello world",
    )
    cursor = SyncCursor(
        account_id=account.id,
        folder_id=folder.id,
        uidvalidity=1,
        last_uid=1,
        uidnext=101,
    )
    event = SyncEvent(
        trace_id=str(uuid.uuid4()),
        account_id=account.id,
        folder_id=folder.id,
        state="initial_sync",
        event_type="sync.start",
        fetched_count=0,
    )
    session.add_all([message, cursor, event])
    await session.commit()

    stored_message = await session.scalar(
        select(Message).where(Message.id == message.id)
    )
    assert stored_message is not None
    assert stored_message.subject == "Hello"
    assert stored_message.to_json == ["demo@example.com"]
    assert stored_message.flags_json == ["\\Seen"]

    stored_cursor = await session.scalar(
        select(SyncCursor).where(SyncCursor.folder_id == folder.id)
    )
    assert stored_cursor is not None
    assert stored_cursor.last_uid == 1

    stored_event = await session.scalar(
        select(SyncEvent).where(SyncEvent.id == event.id)
    )
    assert stored_event is not None
    assert stored_event.event_type == "sync.start"


async def test_message_uid_is_unique_per_folder(
    session: AsyncSession,
) -> None:
    account = Account(
        email="unique@example.com",
        provider="qq",
        username="unique@example.com",
        status="active",
    )
    session.add(account)
    await session.flush()

    folder = Folder(account_id=account.id, name="INBOX")
    session.add(folder)
    await session.flush()

    first = Message(account_id=account.id, folder_id=folder.id, uid=1)
    second = Message(account_id=account.id, folder_id=folder.id, uid=1)
    session.add_all([first, second])

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_deleting_account_cascades_to_folders(
    session: AsyncSession,
) -> None:
    account = Account(
        email="cascade@example.com",
        provider="163",
        username="cascade@example.com",
        status="active",
    )
    session.add(account)
    await session.flush()

    session.add(Folder(account_id=account.id, name="INBOX"))
    await session.commit()

    await session.delete(account)
    await session.commit()

    folder_count = await session.scalar(
        select(func.count()).select_from(Folder)
    )
    assert folder_count == 0
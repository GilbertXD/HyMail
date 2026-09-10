"""Idempotency acceptance tests (PLAN.md v0.0.1 验收标准 1).

"首次同步 1k 封测试邮件后，邮件数量与远端一致，重复同步不产生重复记录。"

The cursor normally prevents any overlap, so a naive "sync twice" test proves
little. These tests also force the engine to re-fetch UIDs it has already
stored, which is the path a RESYNC, a rewind, or a partially committed batch
can actually produce.
"""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.folder import Folder
from hymail_api.db.models.sync import SyncCursor
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import (
    count_messages,
    get_cursor_values,
    get_message_subjects,
)


def _build_engine(
    session_factory: async_sessionmaker[AsyncSession],
    imap_client_factory: Callable[[], ImapClient],
) -> SyncEngine:
    return SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=1,
    )


async def _rewind_cursor(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    folder_name: str,
) -> None:
    """Force the next sync to re-request UIDs that are already stored."""
    async with session_factory() as session, session.begin():
        cursor = await session.scalar(
            select(SyncCursor)
            .join(Folder, Folder.id == SyncCursor.folder_id)
            .where(
                SyncCursor.account_id == account_id,
                Folder.name == folder_name,
            )
        )
        assert cursor is not None
        cursor.last_uid = 0


async def test_repeat_sync_fetches_nothing_new(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    subjects = ["One", "Two", "Three"]
    for uid, subject in enumerate(subjects, start=1):
        mock_server.add_message(message_factory(subject), uid=uid)

    engine = _build_engine(session_factory, imap_client_factory)

    first = await engine.sync_folder(account_id, "INBOX")
    assert first.fetched_count == len(subjects)

    second = await engine.sync_folder(account_id, "INBOX")

    assert second.fetched_count == 0
    assert await count_messages(
        session_factory,
        account_id,
        "INBOX",
    ) == len(subjects)
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == subjects


async def test_refetching_stored_uids_updates_in_place(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    for uid, subject in enumerate(["One", "Two", "Three"], start=1):
        mock_server.add_message(message_factory(subject), uid=uid)

    engine = _build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")
    assert await count_messages(session_factory, account_id, "INBOX") == 3

    # The server re-serves UID 2 with different content, as it would after a
    # RESYNC or if a batch had been committed twice.
    mock_server.folders["INBOX"][1].raw = message_factory("Two Rewritten")
    await _rewind_cursor(session_factory, account_id, "INBOX")

    result = await engine.sync_folder(account_id, "INBOX")

    # All three UIDs were fetched again, but the existing rows were updated
    # rather than appended.
    assert result.fetched_count == 3
    assert await count_messages(session_factory, account_id, "INBOX") == 3
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == ["One", "Two Rewritten", "Three"]

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[1] == 3

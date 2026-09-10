from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.db.models.sync import SyncCursor, SyncEvent
from hymail_api.imap.dto import FetchedMessage, RemoteFolder
from hymail_api.imap.utf7 import decode_mailbox


async def normalize_folder_names(
    session: AsyncSession,
    account_id: UUID,
) -> int:
    """Rewrite folder names that were stored in modified UTF-7 form.

    Rows written before the codec existed kept the raw wire name (for example
    ``&XfJSIJZk-`` instead of ``已删除``), which no longer matches the decoded
    names the IMAP layer now produces. Renaming in place preserves the row id,
    so already-synced messages and cursor progress stay attached.

    When the decoded name is already taken the row is left alone rather than
    merged, because merging would have to reconcile duplicate UIDs.
    """
    folders = list(
        await session.scalars(
            select(Folder).where(Folder.account_id == account_id)
        )
    )
    taken = {folder.name for folder in folders}
    renamed = 0

    for folder in folders:
        decoded = decode_mailbox(folder.name)
        if decoded == folder.name or decoded in taken:
            continue
        taken.discard(folder.name)
        taken.add(decoded)
        folder.name = decoded
        renamed += 1

    if renamed:
        # Sessions run with autoflush disabled, so the renames would otherwise
        # stay in the identity map. A later lookup in the same transaction
        # would read the stale name, miss the row, and insert a duplicate that
        # collides with this very rename on (account_id, name).
        await session.flush()

    return renamed


async def get_or_create_folder(
    session: AsyncSession,
    account_id: UUID,
    remote_folder: RemoteFolder,
) -> Folder:
    """Return the local row for ``remote_folder``, creating it if needed.

    Implemented as an atomic upsert. A plain SELECT-then-INSERT races a
    concurrent refresh or sync: both look, both miss, and the loser trips the
    ``(account_id, name)`` unique constraint.
    """
    statement = (
        sqlite_insert(Folder)
        .values(
            id=uuid4(),
            account_id=account_id,
            name=remote_folder.name,
            delimiter=remote_folder.delimiter,
        )
        .on_conflict_do_update(
            index_elements=[Folder.account_id, Folder.name],
            set_={"delimiter": remote_folder.delimiter},
        )
    )
    await session.execute(statement)

    folder = await session.scalar(
        select(Folder).where(
            Folder.account_id == account_id,
            Folder.name == remote_folder.name,
        )
    )
    if folder is None:
        raise RuntimeError("folder upsert did not persist")
    return folder


async def get_or_create_cursor(
    session: AsyncSession,
    account_id: UUID,
    folder_id: UUID,
) -> SyncCursor:
    cursor = await session.scalar(
        select(SyncCursor).where(
            SyncCursor.account_id == account_id,
            SyncCursor.folder_id == folder_id,
        )
    )
    if cursor is None:
        cursor = SyncCursor(
            account_id=account_id,
            folder_id=folder_id,
        )
        session.add(cursor)
        await session.flush()
    return cursor


async def update_folder_remote_state(
    session: AsyncSession,
    folder: Folder,
    *,
    uidvalidity: int | None,
    uidnext: int | None,
    message_count: int | None = None,
) -> None:
    folder.uidvalidity = uidvalidity
    folder.uidnext = uidnext
    if message_count is not None:
        folder.message_count = message_count


async def delete_messages_for_folder(
    session: AsyncSession,
    folder_id: UUID,
) -> None:
    await session.execute(delete(Message).where(Message.folder_id == folder_id))


async def count_messages(
    session: AsyncSession,
    folder_id: UUID,
) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Message).where(Message.folder_id == folder_id)
    )
    return int(count or 0)


async def upsert_messages(
    session: AsyncSession,
    account_id: UUID,
    folder_id: UUID,
    messages: list[FetchedMessage],
) -> int:
    if not messages:
        return 0

    updated_at = datetime.now(UTC)
    rows = [
        {
            "id": uuid4(),
            "account_id": account_id,
            "folder_id": folder_id,
            "uid": message.uid,
            "message_id": message.parsed.message_id,
            "subject": message.parsed.subject,
            "from_name": message.parsed.from_name,
            "from_addr": message.parsed.from_addr,
            "to_json": message.parsed.to,
            "cc_json": message.parsed.cc,
            "date": message.parsed.date,
            "internal_date": message.internal_date,
            "size": message.size,
            "flags_json": sorted(message.flags),
            "raw_headers": _extract_headers(message.raw_message),
            "body_text": message.parsed.body_text,
            "body_html": message.parsed.body_html,
            "updated_at": updated_at,
        }
        for message in messages
    ]

    statement = sqlite_insert(Message).values(rows)
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[Message.account_id, Message.folder_id, Message.uid],
        set_={
            "message_id": excluded.message_id,
            "subject": excluded.subject,
            "from_name": excluded.from_name,
            "from_addr": excluded.from_addr,
            "to_json": excluded.to_json,
            "cc_json": excluded.cc_json,
            "date": excluded.date,
            "internal_date": excluded.internal_date,
            "size": excluded.size,
            "flags_json": excluded.flags_json,
            "raw_headers": excluded.raw_headers,
            "body_text": excluded.body_text,
            "body_html": excluded.body_html,
            "updated_at": updated_at,
        },
    )
    await session.execute(statement)
    return len(messages)


async def write_event(
    session: AsyncSession,
    *,
    trace_id: str,
    account_id: UUID,
    folder_id: UUID | None,
    state: str,
    event_type: str,
    message: str | None = None,
    uid_from: int | None = None,
    uid_to: int | None = None,
    fetched_count: int = 0,
    duration_ms: int | None = None,
    error_type: str | None = None,
) -> SyncEvent:
    event = SyncEvent(
        trace_id=trace_id,
        account_id=account_id,
        folder_id=folder_id,
        state=state,
        event_type=event_type,
        message=message,
        uid_from=uid_from,
        uid_to=uid_to,
        fetched_count=fetched_count,
        duration_ms=duration_ms,
        error_type=error_type,
    )
    session.add(event)
    return event


def _extract_headers(raw_message: bytes) -> str | None:
    if not raw_message:
        return None
    for separator in (b"\r\n\r\n", b"\n\n"):
        head, found, _ = raw_message.partition(separator)
        if found:
            return head.decode("utf-8", errors="replace")
    return raw_message.decode("utf-8", errors="replace")
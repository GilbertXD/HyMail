from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hymail_api.db.models.folder import Folder
from hymail_api.db.models.message import Message
from hymail_api.db.models.outbox import OutboxAction
from hymail_api.db.models.sync import SyncCursor, SyncEvent
from hymail_api.domain.enums import OutboxActionState
from hymail_api.imap.dto import FetchedMessage, RemoteFolder
from hymail_api.imap.utf7 import decode_mailbox
from hymail_api.sync.flags import flags_to_state


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
    rows = []
    for message in messages:
        is_read, is_starred = flags_to_state(message.flags)
        rows.append(
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
                "is_read": is_read,
                "is_starred": is_starred,
                "raw_headers": _extract_headers(message.raw_message),
                "body_text": message.parsed.body_text,
                "body_html": message.parsed.body_html,
                "updated_at": updated_at,
            }
        )

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
            "is_read": excluded.is_read,
            "is_starred": excluded.is_starred,
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


_RECONCILE_CHUNK = 400


async def attribute_moves_for_new_mail(
    session: AsyncSession,
    account_id: UUID,
    folder_id: UUID,
    message_ids: Sequence[str],
) -> int:
    """Point ghosts at the folder a message just turned up in.

    Runs when mail arrives, so the explanation exists whichever folder the
    batch happens to process first.
    """
    unique_ids = sorted({message_id for message_id in message_ids if message_id})
    if not unique_ids:
        return 0

    result = await session.execute(
        update(Message)
        .where(
            Message.account_id == account_id,
            Message.folder_id != folder_id,
            Message.remote_missing.is_(True),
            Message.message_id.in_(unique_ids),
        )
        .values(moved_to_folder_id=folder_id)
    )
    return result.rowcount or 0


async def attribute_ghost_moves(
    session: AsyncSession,
    account_id: UUID,
    folder_id: UUID,
    uids: set[int],
) -> int:
    """Look for mail flagged missing here in another folder.

    Only a unique destination counts. A Message-ID can legitimately exist in
    two folders at once — a message you CC yourself lives in both Sent and
    INBOX — so an ambiguous match is left unexplained rather than guessed at.
    """
    if not uids:
        return 0

    rows = (
        await session.execute(
            select(
                Message.id,
                Message.message_id,
                Message.moved_to_folder_id,
            ).where(
                Message.folder_id == folder_id,
                Message.uid.in_(sorted(uids)),
                Message.message_id.is_not(None),
            )
        )
    ).all()
    if not rows:
        return 0

    message_ids = [message_id for _, message_id, _ in rows]
    candidates = (
        await session.execute(
            select(Message.message_id, Message.folder_id)
            .where(
                Message.account_id == account_id,
                Message.folder_id != folder_id,
                Message.message_id.in_(message_ids),
                # Another folder's ghost is not evidence that the message is
                # there; only a row the server still confirms counts.
                Message.remote_missing.is_(False),
            )
            .distinct()
        )
    ).all()

    destinations: dict[str, set[UUID]] = {}
    for message_id, candidate_folder_id in candidates:
        destinations.setdefault(message_id, set()).add(candidate_folder_id)

    attributed = 0
    for row_id, message_id, current in rows:
        folders = destinations.get(message_id)
        destination = next(iter(folders)) if folders and len(folders) == 1 else None
        # Recomputed every pass, so a note that no longer holds is dropped
        # rather than left pointing at a folder that no longer has the message.
        if destination == current:
            continue
        await session.execute(
            update(Message)
            .where(Message.id == row_id)
            .values(moved_to_folder_id=destination)
        )
        if destination is not None:
            attributed += 1
    return attributed


async def list_message_uids(
    session: AsyncSession,
    folder_id: UUID,
) -> set[int]:
    uids = await session.scalars(
        select(Message.uid).where(Message.folder_id == folder_id)
    )
    return set(uids)


async def list_remote_missing_uids(
    session: AsyncSession,
    folder_id: UUID,
) -> set[int]:
    uids = await session.scalars(
        select(Message.uid).where(
            Message.folder_id == folder_id,
            Message.remote_missing.is_(True),
        )
    )
    return set(uids)


async def apply_reconcile(
    session: AsyncSession,
    folder_id: UUID,
    *,
    missing: set[int],
    restored: set[int],
) -> None:
    """Record which UIDs are no longer on the server, and which came back.

    Only rows that actually change are touched: clearing the flag on every
    present message would rewrite the whole folder on each reconcile.
    """
    now = datetime.now(UTC)

    for chunk in _chunked(missing, _RECONCILE_CHUNK):
        await session.execute(
            update(Message)
            .where(
                Message.folder_id == folder_id,
                Message.uid.in_(chunk),
            )
            .values(remote_missing=True, remote_missing_at=now)
        )

    for chunk in _chunked(restored, _RECONCILE_CHUNK):
        await session.execute(
            update(Message)
            .where(
                Message.folder_id == folder_id,
                Message.uid.in_(chunk),
                Message.remote_missing.is_(True),
            )
            # The message is back, so any "it moved there" note is stale.
            .values(
                remote_missing=False,
                remote_missing_at=None,
                moved_to_folder_id=None,
            )
        )


def _chunked(values: Iterable[int], size: int) -> Iterator[list[int]]:
    chunk: list[int] = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


async def list_queued_flag_message_ids(
    session: AsyncSession,
    folder_id: UUID,
) -> set[UUID]:
    """Messages whose flag change has not reached the server yet."""
    ids = await session.scalars(
        select(OutboxAction.message_id).where(
            OutboxAction.folder_id == folder_id,
            OutboxAction.state.in_(
                [
                    OutboxActionState.PENDING.value,
                    OutboxActionState.INFLIGHT.value,
                ]
            ),
        )
    )
    return set(ids)


async def apply_flag_reconcile(
    session: AsyncSession,
    folder_id: UUID,
    remote_flags: dict[int, frozenset[str]],
    queued_message_ids: set[UUID],
) -> int:
    """Align local read/starred state with the server's FLAGS.

    Messages with a queued local change are skipped. The server has not heard
    about them yet, so believing its answer would silently undo the click the
    user just made.
    """
    rows = (
        await session.execute(
            select(
                Message.id,
                Message.uid,
                Message.is_read,
                Message.is_starred,
            ).where(Message.folder_id == folder_id)
        )
    ).all()

    changed = 0
    for message_id, uid, is_read, is_starred in rows:
        if message_id in queued_message_ids:
            continue
        flags = remote_flags.get(uid)
        if flags is None:
            continue
        new_read, new_starred = flags_to_state(flags)
        if new_read == is_read and new_starred == is_starred:
            continue
        await session.execute(
            update(Message)
            .where(Message.id == message_id)
            .values(
                is_read=new_read,
                is_starred=new_starred,
                flags_json=sorted(flags),
            )
        )
        changed += 1
    return changed
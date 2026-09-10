import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.account import Account
from hymail_api.db.models.folder import Folder
from hymail_api.db.models.sync import SyncCursor
from hymail_api.domain.enums import AccountStatus, SyncState
from hymail_api.imap.client import ImapClient
from hymail_api.imap.dto import FetchedMessage, FolderSelection, RemoteFolder
from hymail_api.imap.errors import (
    ImapAuthenticationError,
    ImapConnectionError,
    ImapError,
    ImapFolderNotFoundError,
    ImapProtocolError,
    ImapRateLimitError,
)
from hymail_api.sync.backoff import calculate_backoff_delay
from hymail_api.sync.store import (
    count_messages,
    delete_messages_for_folder,
    get_or_create_cursor,
    get_or_create_folder,
    update_folder_remote_state,
    upsert_messages,
    write_event,
)
from hymail_api.sync.types import SyncResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PreparedSync:
    folder_id: UUID
    folder_name: str
    state: SyncState
    start_uid: int
    end_uid: int | None
    uidvalidity: int
    uidnext: int | None


class SyncEngine:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        imap_client_factory: Callable[[], ImapClient],
        batch_size: int = 50,
        max_attempts: int = 3,
        backoff_base_seconds: float = 1.0,
        max_backoff_seconds: float = 300.0,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self._session_factory = session_factory
        self._imap_client_factory = imap_client_factory
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._backoff_base_seconds = backoff_base_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._sleep = sleep_func or asyncio.sleep

    async def sync_folder(
        self,
        account_id: UUID,
        folder_name: str,
        *,
        client: ImapClient | None = None,
    ) -> SyncResult:
        """Sync one folder.

        Pass ``client`` to reuse an already-authenticated connection, which is
        what makes a whole-mailbox batch cost one LOGIN instead of one per
        folder. A shared connection cannot be re-established from in here, so
        it gets a single attempt: the queue re-queues the job with backoff
        instead, which also survives a restart.
        """
        trace_id = str(uuid4())
        started_at = time.monotonic()
        last_error: ImapError | None = None
        max_attempts = self._max_attempts if client is None else 1

        for attempt in range(1, max_attempts + 1):
            try:
                result = await self._sync_once(
                    account_id,
                    folder_name,
                    trace_id,
                    attempt,
                    client,
                )
                result.duration_ms = int((time.monotonic() - started_at) * 1000)
                return result
            except ImapAuthenticationError as exc:
                await self._mark_state(
                    account_id=account_id,
                    folder_name=folder_name,
                    trace_id=trace_id,
                    state=SyncState.AUTH_EXPIRED,
                    event_type="sync.auth_expired",
                    attempts=attempt,
                    error=exc,
                )
                raise
            except (
                ImapConnectionError,
                ImapRateLimitError,
                ImapProtocolError,
            ) as exc:
                last_error = exc
                await self._mark_state(
                    account_id=account_id,
                    folder_name=folder_name,
                    trace_id=trace_id,
                    state=SyncState.ERROR_BACKOFF,
                    event_type="sync.backoff",
                    attempts=attempt,
                    error=exc,
                )
                if attempt >= max_attempts:
                    raise
                delay = calculate_backoff_delay(
                    attempt,
                    base_seconds=self._backoff_base_seconds,
                    max_seconds=self._max_backoff_seconds,
                )
                logger.warning(
                    "sync backoff account_id=%s folder=%s attempt=%s delay=%s",
                    account_id,
                    folder_name,
                    attempt,
                    delay,
                )
                await self._sleep(delay)
            except asyncio.CancelledError:
                await self._mark_state(
                    account_id=account_id,
                    folder_name=folder_name,
                    trace_id=trace_id,
                    state=SyncState.IDLE,
                    event_type="sync.cancelled",
                    attempts=0,
                    error=None,
                )
                raise

        if last_error is not None:
            raise last_error
        raise ImapError("sync failed without a recoverable error")

    async def _sync_once(
        self,
        account_id: UUID,
        folder_name: str,
        trace_id: str,
        attempt: int,
        client: ImapClient | None = None,
    ) -> SyncResult:
        owned = client is None
        active = client if client is not None else self._imap_client_factory()
        try:
            if owned:
                await active.connect()
            folders = await active.list_folders()
            remote_folder = _find_remote_folder(folders, folder_name)
            if remote_folder is None:
                raise ImapFolderNotFoundError(
                    f"IMAP folder not found: {folder_name}"
                )

            selection = await active.select_folder(folder_name)
            if selection.uidvalidity is None:
                raise ImapProtocolError("server did not return UIDVALIDITY")

            prepared = await self._prepare_sync(
                account_id,
                remote_folder,
                selection,
                trace_id,
                attempt,
            )

            total_fetched = 0
            buffer: list[FetchedMessage] = []
            if prepared.end_uid is None or prepared.start_uid <= prepared.end_uid:
                async for message in active.fetch_messages(
                    folder_name,
                    prepared.start_uid,
                    prepared.end_uid,
                    batch_size=self._batch_size,
                ):
                    buffer.append(message)
                    if len(buffer) >= self._batch_size:
                        await self._commit_batch(
                            account_id,
                            prepared.folder_id,
                            buffer,
                            prepared.state,
                            trace_id,
                            attempt,
                        )
                        total_fetched += len(buffer)
                        buffer.clear()

            if buffer:
                await self._commit_batch(
                    account_id,
                    prepared.folder_id,
                    buffer,
                    prepared.state,
                    trace_id,
                    attempt,
                )
                total_fetched += len(buffer)

            return await self._finalize_sync(
                account_id,
                prepared,
                trace_id,
                total_fetched,
            )
        finally:
            if owned:
                await active.close()

    async def _prepare_sync(
        self,
        account_id: UUID,
        remote_folder: RemoteFolder,
        selection: FolderSelection,
        trace_id: str,
        attempt: int,
    ) -> _PreparedSync:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            folder = await get_or_create_folder(
                session,
                account_id,
                remote_folder,
            )
            await update_folder_remote_state(
                session,
                folder,
                uidvalidity=selection.uidvalidity,
                uidnext=selection.uidnext,
                message_count=selection.exists,
            )
            cursor = await get_or_create_cursor(
                session,
                account_id,
                folder.id,
            )

            previous_uidvalidity = cursor.uidvalidity
            if (
                previous_uidvalidity is not None
                and previous_uidvalidity != selection.uidvalidity
            ):
                state = SyncState.RESYNC
                await delete_messages_for_folder(session, folder.id)
                cursor.last_uid = 0
            elif previous_uidvalidity is None:
                state = SyncState.INITIAL_SYNC
                cursor.last_uid = 0
            else:
                state = SyncState.INCREMENTAL_SYNC

            cursor.uidvalidity = selection.uidvalidity
            cursor.uidnext = selection.uidnext
            cursor.state = state.value
            cursor.attempts = attempt
            cursor.last_error = None
            cursor.last_sync_at = now

            await write_event(
                session,
                trace_id=trace_id,
                account_id=account_id,
                folder_id=folder.id,
                state=state.value,
                event_type="sync.start",
                message=f"folder={remote_folder.name}",
            )
            await session.flush()

            start_uid = max(cursor.last_uid + 1, 1)
            end_uid = (
                selection.uidnext - 1
                if selection.uidnext is not None
                else None
            )
            return _PreparedSync(
                folder_id=folder.id,
                folder_name=folder.name,
                state=state,
                start_uid=start_uid,
                end_uid=end_uid,
                uidvalidity=selection.uidvalidity,
                uidnext=selection.uidnext,
            )

    async def _commit_batch(
        self,
        account_id: UUID,
        folder_id: UUID,
        messages: Sequence[FetchedMessage],
        state: SyncState,
        trace_id: str,
        attempt: int,
    ) -> None:
        if not messages:
            return

        now = datetime.now(UTC)
        uids = [message.uid for message in messages]
        min_uid = min(uids)
        max_uid = max(uids)

        async with self._session_factory() as session, session.begin():
            await upsert_messages(
                session,
                account_id,
                folder_id,
                list(messages),
            )
            cursor = await session.scalar(
                select(SyncCursor).where(
                    SyncCursor.account_id == account_id,
                    SyncCursor.folder_id == folder_id,
                )
            )
            if cursor is None:
                raise RuntimeError("sync cursor not found for batch commit")

            cursor.last_uid = max(cursor.last_uid, max_uid)
            cursor.uidnext = max(cursor.uidnext or 0, max_uid + 1)
            cursor.state = state.value
            cursor.attempts = attempt
            cursor.last_error = None
            cursor.last_sync_at = now

            folder = await session.get(Folder, folder_id)
            if folder is not None:
                folder.message_count = await count_messages(session, folder_id)

            await write_event(
                session,
                trace_id=trace_id,
                account_id=account_id,
                folder_id=folder_id,
                state=state.value,
                event_type="sync.batch",
                uid_from=min_uid,
                uid_to=max_uid,
                fetched_count=len(messages),
            )

    async def _finalize_sync(
        self,
        account_id: UUID,
        prepared: _PreparedSync,
        trace_id: str,
        fetched_count: int,
    ) -> SyncResult:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            cursor = await session.scalar(
                select(SyncCursor).where(
                    SyncCursor.account_id == account_id,
                    SyncCursor.folder_id == prepared.folder_id,
                )
            )
            if cursor is None:
                raise RuntimeError("sync cursor not found for finalize")

            cursor.state = SyncState.IDLE.value
            cursor.attempts = 0
            cursor.last_error = None
            cursor.uidvalidity = prepared.uidvalidity
            cursor.uidnext = max(
                cursor.uidnext or 0,
                prepared.uidnext or 0,
            )
            cursor.last_sync_at = now

            folder = await session.get(Folder, prepared.folder_id)
            if folder is not None:
                folder.message_count = await count_messages(
                    session,
                    prepared.folder_id,
                )

            await write_event(
                session,
                trace_id=trace_id,
                account_id=account_id,
                folder_id=prepared.folder_id,
                state=SyncState.IDLE.value,
                event_type="sync.completed",
                fetched_count=fetched_count,
            )

            return SyncResult(
                account_id=account_id,
                folder_id=prepared.folder_id,
                folder_name=prepared.folder_name,
                state=SyncState.IDLE,
                fetched_count=fetched_count,
                last_uid=cursor.last_uid,
                uidvalidity=cursor.uidvalidity,
                uidnext=cursor.uidnext,
                attempts=0,
                trace_id=trace_id,
            )

    async def _mark_state(
        self,
        *,
        account_id: UUID,
        folder_name: str,
        trace_id: str,
        state: SyncState,
        event_type: str,
        attempts: int,
        error: BaseException | None,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            account = await session.get(Account, account_id)
            if account is not None and state is SyncState.AUTH_EXPIRED:
                account.status = AccountStatus.AUTH_EXPIRED.value

            folder = await session.scalar(
                select(Folder).where(
                    Folder.account_id == account_id,
                    Folder.name == folder_name,
                )
            )
            folder_id = folder.id if folder is not None else None

            if folder_id is not None:
                cursor = await session.scalar(
                    select(SyncCursor).where(
                        SyncCursor.account_id == account_id,
                        SyncCursor.folder_id == folder_id,
                    )
                )
                if cursor is not None:
                    cursor.state = state.value
                    cursor.attempts = attempts
                    cursor.last_error = str(error) if error is not None else None
                    cursor.last_sync_at = now

            await write_event(
                session,
                trace_id=trace_id,
                account_id=account_id,
                folder_id=folder_id,
                state=state.value,
                event_type=event_type,
                message=str(error) if error is not None else None,
                error_type=type(error).__name__ if error is not None else None,
            )


def _find_remote_folder(
    folders: Sequence[RemoteFolder],
    folder_name: str,
) -> RemoteFolder | None:
    for folder in folders:
        if folder.name == folder_name:
            return folder
    return None
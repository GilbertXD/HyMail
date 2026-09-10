"""Crash recovery acceptance tests (PLAN.md v0.0.1 验收标准 6).

"同步过程中杀掉后端进程再启动，能从最后一次已提交事务恢复。"

A killed process never runs cleanup code, so the only state that survives is
what an already-committed transaction wrote. ``SimulatedCrash`` reproduces
exactly that: it is deliberately *not* an ``ImapError``, so the engine's
``ERROR_BACKOFF`` handling never runs and the cursor is left frozen in its
in-flight state. Recovery must therefore come purely from the cursor that the
last committed batch wrote.
"""

from collections.abc import AsyncIterator, Callable
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.imap.client import ImapClient
from hymail_api.imap.dto import FetchedMessage, FolderSelection, RemoteFolder
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import (
    count_messages,
    get_cursor_values,
    get_message_subjects,
)


class SimulatedCrash(RuntimeError):
    """Stands in for the backend process dying in the middle of a sync."""


class CrashingImapClient:
    """Delegates to a real ``ImapClient`` but dies partway through FETCH.

    The engine only ever calls these five methods, so a duck-typed wrapper is
    enough to inject a crash at a precise point of the FETCH stream.
    """

    def __init__(self, inner: ImapClient, *, messages_before_crash: int) -> None:
        self._inner = inner
        self._messages_before_crash = messages_before_crash

    async def connect(self) -> None:
        await self._inner.connect()

    async def close(self) -> None:
        await self._inner.close()

    async def list_folders(self) -> list[RemoteFolder]:
        return await self._inner.list_folders()

    async def select_folder(self, folder: str) -> FolderSelection:
        return await self._inner.select_folder(folder)

    async def fetch_messages(
        self,
        folder: str,
        start_uid: int,
        end_uid: int | None = None,
        *,
        batch_size: int = 50,
        include_body: bool = True,
    ) -> AsyncIterator[FetchedMessage]:
        yielded = 0
        async for message in self._inner.fetch_messages(
            folder,
            start_uid,
            end_uid,
            batch_size=batch_size,
            include_body=include_body,
        ):
            if yielded >= self._messages_before_crash:
                raise SimulatedCrash("process died mid-sync")
            yielded += 1
            yield message
        if yielded >= self._messages_before_crash:
            raise SimulatedCrash("process died mid-sync")


async def test_crash_mid_sync_resumes_from_last_committed_batch(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    subjects = ["One", "Two", "Three", "Four", "Five"]
    for uid, subject in enumerate(subjects, start=1):
        mock_server.add_message(message_factory(subject), uid=uid)

    def crashing_factory() -> ImapClient:
        return CrashingImapClient(
            imap_client_factory(),
            messages_before_crash=2,
        )

    # --- run 1: die after the first committed batch -----------------------
    first_engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=crashing_factory,
        batch_size=2,
        max_attempts=1,
    )
    with pytest.raises(SimulatedCrash):
        await first_engine.sync_folder(account_id, "INBOX")

    # Only the committed batch survived, and nothing tidied the cursor up:
    # it is still parked in the in-flight state the batch transaction wrote.
    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[0] == "initial_sync"
    assert cursor[1] == 2
    assert await count_messages(session_factory, account_id, "INBOX") == 2

    # --- run 2: fresh process, fresh engine, healthy server ---------------
    second_engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=2,
        max_attempts=1,
    )
    result = await second_engine.sync_folder(account_id, "INBOX")

    # UIDs 1-2 were already committed, so only 3-5 are re-fetched.
    assert result.fetched_count == 3
    assert result.last_uid == 5
    assert await count_messages(session_factory, account_id, "INBOX") == 5
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == subjects

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[0] == "idle"
    assert cursor[1] == 5


async def test_crash_recovery_holds_at_scale(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    total = 1000
    for uid in range(1, total + 1):
        mock_server.add_message(message_factory(f"Scale {uid:04d}"), uid=uid)

    def crashing_factory() -> ImapClient:
        return CrashingImapClient(
            imap_client_factory(),
            messages_before_crash=350,
        )

    first_engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=crashing_factory,
        batch_size=100,
        max_attempts=1,
    )
    with pytest.raises(SimulatedCrash):
        await first_engine.sync_folder(account_id, "INBOX")

    # Three whole batches of 100 were committed; the partial fourth was not.
    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[1] == 300
    assert await count_messages(session_factory, account_id, "INBOX") == 300

    second_engine = SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=100,
        max_attempts=1,
    )
    result = await second_engine.sync_folder(account_id, "INBOX")

    assert result.fetched_count == total - 300
    assert result.last_uid == total
    assert await count_messages(session_factory, account_id, "INBOX") == total

    cursor = await get_cursor_values(session_factory, account_id, "INBOX")
    assert cursor is not None
    assert cursor[0] == "idle"
    assert cursor[1] == total

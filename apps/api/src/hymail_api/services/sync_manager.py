import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.db.models.account import Account
from hymail_api.imap.client import ImapClient
from hymail_api.sync.engine import SyncEngine


@dataclass(slots=True)
class SyncTaskStatus:
    account_id: UUID
    folder: str
    running: bool = False
    state: str = "idle"
    trace_id: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SyncManager:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client_factory: Callable[[Account], ImapClient],
    ) -> None:
        self._session_factory = session_factory
        self._client_factory = client_factory
        self._tasks: dict[tuple[UUID, str], asyncio.Task[None]] = {}
        self._statuses: dict[tuple[UUID, str], SyncTaskStatus] = {}

    async def start(
        self,
        account_id: UUID,
        folder: str,
    ) -> SyncTaskStatus:
        key = (account_id, folder)
        task = self._tasks.get(key)
        if task is not None and not task.done():
            return self._statuses[key]

        status = SyncTaskStatus(
            account_id=account_id,
            folder=folder,
            running=True,
            state="starting",
            started_at=datetime.now(UTC),
        )
        self._statuses[key] = status
        self._tasks[key] = asyncio.create_task(
            self._run(account_id, folder, status)
        )
        return status

    async def cancel(self, account_id: UUID, folder: str) -> bool:
        key = (account_id, folder)
        task = self._tasks.get(key)
        if task is None or task.done():
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True

    def get_status(
        self,
        account_id: UUID,
        folder: str,
    ) -> SyncTaskStatus | None:
        return self._statuses.get((account_id, folder))

    async def _run(
        self,
        account_id: UUID,
        folder: str,
        status: SyncTaskStatus,
    ) -> None:
        key = (account_id, folder)
        try:
            async with self._session_factory() as session:
                account = await session.get(Account, account_id)
            if account is None:
                raise ValueError(f"account not found: {account_id}")

            engine = SyncEngine(
                session_factory=self._session_factory,
                imap_client_factory=lambda: self._client_factory(account),
            )
            status.state = "running"
            result = await engine.sync_folder(account_id, folder)
            status.state = result.state.value
            status.trace_id = result.trace_id
        except asyncio.CancelledError:
            status.state = "idle"
            status.error = "cancelled"
        except Exception as exc:
            status.state = "error"
            status.error = str(exc)
        finally:
            status.running = False
            status.finished_at = datetime.now(UTC)
            self._tasks.pop(key, None)
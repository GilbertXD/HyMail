from dataclasses import dataclass
from uuid import UUID

from hymail_api.domain.enums import SyncState


@dataclass(slots=True)
class SyncResult:
    account_id: UUID
    folder_id: UUID
    folder_name: str
    state: SyncState
    fetched_count: int
    last_uid: int
    uidvalidity: int | None
    uidnext: int | None
    attempts: int
    trace_id: str
    duration_ms: int = 0
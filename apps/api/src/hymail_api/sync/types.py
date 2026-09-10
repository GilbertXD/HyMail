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


@dataclass(slots=True)
class ReconcileResult:
    """Outcome of comparing a folder against the server's UID set."""

    account_id: UUID
    folder_id: UUID
    folder_name: str
    synced_count: int
    newly_missing: int
    restored: int
    flags_changed: int
    remote_total: int
    local_total: int
    trace_id: str
    uidvalidity: int | None
    skipped_mass_flagging: bool = False
    duration_ms: int = 0
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SyncTriggerRequest(BaseModel):
    folder: str = "INBOX"


class SyncCancelRequest(BaseModel):
    folder: str = "INBOX"


class SyncCancelResponse(BaseModel):
    cancelled: bool


class SyncStatusRead(BaseModel):
    account_id: UUID
    folder: str
    running: bool
    state: str
    last_uid: int
    uidvalidity: int | None
    uidnext: int | None
    attempts: int
    last_error: str | None
    trace_id: str | None
    last_sync_at: datetime | None


class SyncEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trace_id: str
    folder_id: UUID | None
    state: str
    event_type: str
    message: str | None
    uid_from: int | None
    uid_to: int | None
    fetched_count: int
    duration_ms: int | None
    error_type: str | None
    created_at: datetime
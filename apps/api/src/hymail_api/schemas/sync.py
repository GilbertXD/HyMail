from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SyncTriggerRequest(BaseModel):
    folder: str = "INBOX"


class SyncTriggerAllRequest(BaseModel):
    """An empty body syncs every folder that still exists on the server."""

    folder_names: list[str] | None = None


class SyncCancelRequest(BaseModel):
    folder: str | None = None
    batch_id: UUID | None = None


class SyncCancelResponse(BaseModel):
    cancelled: int


class SyncTriggerResponse(BaseModel):
    batch_id: UUID
    job_ids: list[UUID]
    queued: int
    skipped: int = 0


class SyncBatchRead(BaseModel):
    batch_id: UUID
    total: int
    queued: int
    running: int
    success: int
    failed: int
    cancelled: int
    state: str
    current_folder: str | None
    last_error: str | None


class SyncJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    folder_id: UUID
    folder_name: str
    batch_id: UUID
    kind: str
    state: str
    priority: int
    attempts: int
    last_error: str | None
    not_before: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


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

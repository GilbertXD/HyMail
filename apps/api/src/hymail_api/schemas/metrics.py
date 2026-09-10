from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FolderMetricsRead(BaseModel):
    folder_id: UUID
    folder_name: str
    runs: int
    failures: int
    retries: int
    fetched: int
    avg_duration_ms: int | None
    p95_duration_ms: int | None
    last_sync_at: datetime | None
    last_error: str | None


class OutboxMetricsRead(BaseModel):
    pending: int
    inflight: int
    success: int
    failed: int
    abandoned: int
    outstanding: int


class MetricsRead(BaseModel):
    window_hours: int
    generated_at: datetime
    runs: int
    failures: int
    failure_rate: float
    retries: int
    fetched: int
    avg_duration_ms: int | None
    p95_duration_ms: int | None
    folders: list[FolderMetricsRead]
    outbox: OutboxMetricsRead

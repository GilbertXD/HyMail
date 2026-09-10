"""Structured metrics over the sync queue, the events and the outbox.

Answers the questions PLAN.md asks of v0.1: how long syncs take, how much mail
they fetch, how often they fail and how much retrying that costs. Everything
is derived from rows the pipeline already writes, so there is no extra
bookkeeping to drift out of step.

Runs come from ``sync_job`` (it knows attempts and terminal state) while
fetched counts and durations come from ``sync.completed`` events; mixing the
two keeps each number on the source that actually owns it.
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hymail_api.db.models.folder import Folder
from hymail_api.db.models.outbox import OutboxAction
from hymail_api.db.models.sync import SyncCursor, SyncEvent, SyncJob
from hymail_api.domain.enums import OutboxActionState, SyncJobState

_TIMED_RUN_STATES = (
    SyncJobState.SUCCESS.value,
    SyncJobState.FAILED.value,
)
_OUTBOX_STATES = (
    OutboxActionState.PENDING.value,
    OutboxActionState.INFLIGHT.value,
    OutboxActionState.SUCCESS.value,
    OutboxActionState.FAILED.value,
    OutboxActionState.ABANDONED.value,
)


@dataclass(slots=True)
class _Bucket:
    runs: int = 0
    failures: int = 0
    retries: int = 0
    fetched: int = 0
    durations: list[int] = field(default_factory=list)
    last_error: str | None = None


@dataclass(slots=True)
class FolderMetrics:
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


@dataclass(slots=True)
class OutboxMetrics:
    pending: int
    inflight: int
    success: int
    failed: int
    abandoned: int

    @property
    def outstanding(self) -> int:
        return self.pending + self.inflight


@dataclass(slots=True)
class MetricsSnapshot:
    window_hours: int
    generated_at: datetime
    runs: int
    failures: int
    retries: int
    fetched: int
    avg_duration_ms: int | None
    p95_duration_ms: int | None
    folders: list[FolderMetrics]
    outbox: OutboxMetrics

    @property
    def failure_rate(self) -> float:
        return self.failures / self.runs if self.runs else 0.0


def percentile(values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile; SQLite has no percentile function.

    Rank is ``ceil(fraction * n)``, so p95 of ten values is the largest one
    rather than an interpolation between the top two.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(fraction * len(ordered))
    index = min(max(rank - 1, 0), len(ordered) - 1)
    return ordered[index]


def _average(values: list[int]) -> int | None:
    if not values:
        return None
    return int(sum(values) / len(values))


async def collect_metrics(
    session: AsyncSession,
    account_id: UUID,
    *,
    window_hours: int = 24,
) -> MetricsSnapshot:
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)

    folders = dict(
        (
            await session.execute(
                select(Folder.id, Folder.name).where(
                    Folder.account_id == account_id
                )
            )
        ).all()
    )

    job_rows = (
        await session.execute(
            select(
                SyncJob.folder_id,
                SyncJob.state,
                SyncJob.attempts,
                SyncJob.last_error,
                SyncJob.finished_at,
            ).where(
                SyncJob.account_id == account_id,
                SyncJob.created_at >= since,
            )
        )
    ).all()

    event_rows = (
        await session.execute(
            select(
                SyncEvent.folder_id,
                func.coalesce(func.sum(SyncEvent.fetched_count), 0),
                func.count(),
            )
            .where(
                SyncEvent.account_id == account_id,
                SyncEvent.event_type == "sync.completed",
                SyncEvent.created_at >= since,
            )
            .group_by(SyncEvent.folder_id)
        )
    ).all()

    duration_rows = (
        await session.execute(
            select(SyncEvent.folder_id, SyncEvent.duration_ms).where(
                SyncEvent.account_id == account_id,
                SyncEvent.event_type == "sync.completed",
                SyncEvent.duration_ms.is_not(None),
                SyncEvent.created_at >= since,
            )
        )
    ).all()

    cursor_rows = (
        await session.execute(
            select(SyncCursor.folder_id, SyncCursor.last_sync_at).where(
                SyncCursor.account_id == account_id
            )
        )
    ).all()

    outbox_counts = dict(
        (
            await session.execute(
                select(OutboxAction.state, func.count())
                .where(OutboxAction.account_id == account_id)
                .group_by(OutboxAction.state)
            )
        ).all()
    )

    per_folder: dict[UUID, _Bucket] = {
        folder_id: _Bucket() for folder_id in folders
    }

    def bucket_for(folder_id: UUID) -> _Bucket:
        # A job or event can outlive its folder row only briefly, but the
        # metrics must not KeyError if it does.
        return per_folder.setdefault(folder_id, _Bucket())

    for folder_id, state, attempts, last_error, _finished in job_rows:
        bucket = bucket_for(folder_id)
        if state in _TIMED_RUN_STATES:
            bucket.runs += 1
        if state == SyncJobState.FAILED.value:
            bucket.failures += 1
        # The first attempt is the baseline; the rest are retrying.
        bucket.retries += max(attempts - 1, 0)
        if last_error is not None and bucket.last_error is None:
            bucket.last_error = last_error

    for folder_id, fetched, _count in event_rows:
        bucket_for(folder_id).fetched = int(fetched or 0)

    for folder_id, duration in duration_rows:
        if duration is not None:
            bucket_for(folder_id).durations.append(int(duration))

    last_sync = {folder_id: value for folder_id, value in cursor_rows}

    folder_metrics: list[FolderMetrics] = []
    for folder_id, name in folders.items():
        bucket = per_folder[folder_id]
        folder_metrics.append(
            FolderMetrics(
                folder_id=folder_id,
                folder_name=name,
                runs=bucket.runs,
                failures=bucket.failures,
                retries=bucket.retries,
                fetched=bucket.fetched,
                avg_duration_ms=_average(bucket.durations),
                p95_duration_ms=percentile(bucket.durations, 0.95),
                last_sync_at=last_sync.get(folder_id),
                last_error=bucket.last_error,
            )
        )

    folder_metrics.sort(key=lambda item: (-item.fetched, item.folder_name))

    all_durations = [
        duration for bucket in per_folder.values() for duration in bucket.durations
    ]

    return MetricsSnapshot(
        window_hours=window_hours,
        generated_at=now,
        runs=sum(item.runs for item in folder_metrics),
        failures=sum(item.failures for item in folder_metrics),
        retries=sum(item.retries for item in folder_metrics),
        fetched=sum(item.fetched for item in folder_metrics),
        avg_duration_ms=_average(all_durations),
        p95_duration_ms=percentile(all_durations, 0.95),
        folders=folder_metrics,
        outbox=OutboxMetrics(
            **{
                state: int(outbox_counts.get(state, 0))
                for state in _OUTBOX_STATES
            }
        ),
    )

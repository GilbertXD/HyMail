from enum import IntEnum, StrEnum


class AccountStatus(StrEnum):
    ACTIVE = "active"
    AUTH_EXPIRED = "auth_expired"
    DISABLED = "disabled"


class SyncState(StrEnum):
    IDLE = "idle"
    INITIAL_SYNC = "initial_sync"
    INCREMENTAL_SYNC = "incremental_sync"
    RESYNC = "resync"
    RECONCILE = "reconcile"
    ERROR_BACKOFF = "error_backoff"
    AUTH_EXPIRED = "auth_expired"


class SyncJobState(StrEnum):
    """Lifecycle of one queued folder sync."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncJobKind(StrEnum):
    """What a queued job should do to its folder."""

    SYNC = "sync"
    RECONCILE = "reconcile"


class SyncPriority(IntEnum):
    """Lower runs first.

    Mirrors the ordering in PLAN.md: work the user asked for beats background
    work, so a manual sync is never stuck behind a sweep.
    """

    USER = 0
    POLL = 10
    RECONCILE = 20
    INDEX = 30


class SyncBatchState(StrEnum):
    """Aggregate state of a batch, derived from its jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EMPTY = "empty"


class OutboxActionType(StrEnum):
    """A local change that has to reach the server."""

    MARK_READ = "mark_read"
    STAR = "star"


class OutboxActionState(StrEnum):
    """Lifecycle of one queued write, mirroring PLAN.md."""

    PENDING = "pending"
    INFLIGHT = "inflight"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"

from enum import StrEnum


class AccountStatus(StrEnum):
    ACTIVE = "active"
    AUTH_EXPIRED = "auth_expired"
    DISABLED = "disabled"


class SyncState(StrEnum):
    IDLE = "idle"
    INITIAL_SYNC = "initial_sync"
    INCREMENTAL_SYNC = "incremental_sync"
    RESYNC = "resync"
    ERROR_BACKOFF = "error_backoff"
    AUTH_EXPIRED = "auth_expired"
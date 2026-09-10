from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from hymail_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from hymail_api.domain.enums import SyncJobState, SyncPriority


class SyncCursor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sync_cursor"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "folder_id",
            name="uq_sync_cursor_account_id_folder_id",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    folder_id: Mapped[UUID] = mapped_column(
        ForeignKey("folder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uidvalidity: Mapped[int | None] = mapped_column()
    last_uid: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    uidnext: Mapped[int | None] = mapped_column()
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="idle",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class SyncEvent(Base):
    __tablename__ = "sync_event"
    __table_args__ = (
        Index("ix_sync_event_account_id_id", "account_id", "id"),
        Index("ix_sync_event_folder_id_id", "folder_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    trace_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    folder_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folder.id", ondelete="CASCADE"),
        index=True,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    uid_from: Mapped[int | None] = mapped_column(Integer)
    uid_to: Mapped[int | None] = mapped_column(Integer)
    fetched_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SyncJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable request to sync one folder.

    The queue lives in the database rather than in memory so that a restart
    resumes unfinished work and so that ``attempts``, backoff and cancellation
    survive a crash. ``batch_id`` groups the jobs of a single "sync
    everything" request; batch progress is an aggregate over it.
    """

    __tablename__ = "sync_job"
    __table_args__ = (
        Index(
            "ix_sync_job_account_state_priority",
            "account_id",
            "state",
            "priority",
        ),
        Index("ix_sync_job_batch_id", "batch_id"),
        Index("ix_sync_job_folder_id", "folder_id"),
    )

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    folder_id: Mapped[UUID] = mapped_column(
        ForeignKey("folder.id", ondelete="CASCADE"),
        nullable=False,
    )
    batch_id: Mapped[UUID] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SyncJobState.QUEUED.value,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=int(SyncPriority.USER),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    # Set when a retry has to wait for its backoff to elapse.
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A running job owns a lease; an expired lease means the worker died.
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
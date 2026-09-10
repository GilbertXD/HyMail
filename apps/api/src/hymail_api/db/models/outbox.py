from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hymail_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from hymail_api.domain.enums import OutboxActionState


class OutboxAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A local flag change on its way to the server.

    Optimistic UI is only honest if the intent survives a crash, so it is
    written down here before the interface claims it happened. Superseding
    pending actions for the same message and type is what keeps a double
    toggle from sending two contradictory writes.
    """

    __tablename__ = "outbox_action"
    __table_args__ = (
        Index("ix_outbox_action_account_state", "account_id", "state"),
        Index("ix_outbox_action_message_type", "message_id", "type"),
    )

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"),
        nullable=False,
    )
    folder_id: Mapped[UUID] = mapped_column(
        ForeignKey("folder.id", ondelete="CASCADE"),
        nullable=False,
    )
    uid: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OutboxActionState.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

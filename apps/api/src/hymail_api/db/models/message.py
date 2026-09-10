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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from hymail_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "message"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "folder_id",
            "uid",
            name="uq_message_account_id_folder_id_uid",
        ),
        Index("ix_message_folder_id_date", "folder_id", "date"),
        Index("ix_message_folder_id_uid", "folder_id", "uid"),
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
    uid: Mapped[int] = mapped_column(nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(998))
    subject: Mapped[str | None] = mapped_column(Text)
    from_name: Mapped[str | None] = mapped_column(String(255))
    from_addr: Mapped[str | None] = mapped_column(String(320))
    to_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    cc_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    internal_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    size: Mapped[int | None] = mapped_column(Integer)
    flags_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    raw_headers: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
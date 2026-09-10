from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hymail_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Folder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "folder"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "name",
            name="uq_folder_account_id_name",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    delimiter: Mapped[str | None] = mapped_column(String(16))
    uidvalidity: Mapped[int | None] = mapped_column()
    uidnext: Mapped[int | None] = mapped_column()
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
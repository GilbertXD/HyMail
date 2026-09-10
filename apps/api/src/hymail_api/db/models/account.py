from __future__ import annotations

from sqlalchemy import Boolean, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hymail_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Account(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("email", name="uq_account_email"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="custom",
    )
    imap_host: Mapped[str | None] = mapped_column(String(255))
    imap_port: Mapped[int | None] = mapped_column()
    imap_ssl: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    username: Mapped[str | None] = mapped_column(String(320))
    secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
    )
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MessageSummary(BaseModel):
    id: UUID
    folder_id: UUID
    uid: int
    subject: str | None
    from_name: str | None
    from_addr: str | None
    date: datetime | None
    size: int | None
    flags: list[str]
    folder_name: str | None = None
    account_email: str | None = None
    # Set by reconciliation when the UID is gone from the server.
    remote_missing: bool = False
    # Mirrors the \Seen and \Flagged IMAP flags.
    is_read: bool = False
    is_starred: bool = False
    # "pending" / "inflight" / "failed" while a local flag change is still on
    # its way to the server, so the UI can be honest about it.
    outbox_state: str | None = None


class MessageFlagUpdate(BaseModel):
    """A local read/starred change.

    Absent fields are left alone, so the two toggles never fight each other.
    """

    is_read: bool | None = None
    is_starred: bool | None = None


class MessageDetail(MessageSummary):
    to: list[str]
    cc: list[str]
    raw_headers: str | None
    body_text: str | None
    body_html: str | None
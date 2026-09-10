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


class MessageDetail(MessageSummary):
    to: list[str]
    cc: list[str]
    raw_headers: str | None
    body_text: str | None
    body_html: str | None
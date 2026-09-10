from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OutboxActionRead(BaseModel):
    id: UUID
    message_id: UUID
    folder_id: UUID
    folder_name: str
    uid: int
    type: str
    state: str
    value: bool
    attempts: int
    last_error: str | None
    next_retry_at: datetime | None
    created_at: datetime
    subject: str | None


class OutboxMutationResponse(BaseModel):
    updated: bool

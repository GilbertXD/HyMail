from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    name: str
    delimiter: str | None
    uidvalidity: int | None
    uidnext: int | None
    message_count: int
    last_sync_at: datetime | None
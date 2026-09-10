from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccountBase(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    provider: str = Field(default="custom", max_length=32)
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_ssl: bool = True
    username: str | None = Field(default=None, max_length=320)


class AccountCreate(AccountBase):
    secret: str = Field(min_length=1, max_length=1024)


class AccountRead(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    created_at: datetime
    updated_at: datetime


class ConnectionTestRequest(AccountBase):
    secret: str = Field(min_length=1, max_length=1024)


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str
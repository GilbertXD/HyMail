from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RemoteFolder:
    name: str
    delimiter: str | None
    flags: frozenset[str]


@dataclass(frozen=True, slots=True)
class FolderSelection:
    name: str
    exists: int
    uidvalidity: int | None
    uidnext: int | None
    flags: frozenset[str]


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    message_id: str | None
    subject: str | None
    from_name: str | None
    from_addr: str | None
    to: list[str]
    cc: list[str]
    date: datetime | None
    body_text: str | None
    body_html: str | None


@dataclass(frozen=True, slots=True)
class FetchedMessage:
    uid: int
    flags: frozenset[str]
    internal_date: datetime | None
    size: int | None
    raw_message: bytes
    parsed: ParsedMessage
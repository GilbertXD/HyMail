from datetime import datetime
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from hymail_api.imap.dto import ParsedMessage


def parse_message(raw_message: bytes) -> ParsedMessage:
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    from_name, from_addr = _parse_from(message)
    return ParsedMessage(
        message_id=_header(message, "Message-ID"),
        subject=_header(message, "Subject"),
        from_name=from_name,
        from_addr=from_addr,
        to=_address_list(message, "To"),
        cc=_address_list(message, "Cc"),
        date=_parse_date(message.get("Date")),
        body_text=_extract_body(message, "text/plain"),
        body_html=_extract_body(message, "text/html"),
    )


def _header(message: Message, name: str) -> str | None:
    value = message.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_from(message: Message) -> tuple[str | None, str | None]:
    raw = _header(message, "From")
    if not raw:
        return None, None
    addresses = getaddresses([raw])
    if not addresses:
        return None, None
    name, address = addresses[0]
    return name or None, address or None


def _address_list(message: Message, header_name: str) -> list[str]:
    values = message.get_all(header_name, [])
    if not values:
        return []
    result: list[str] = []
    for name, address in getaddresses([str(value) for value in values]):
        if not address:
            continue
        result.append(f"{name} <{address}>" if name else address)
    return result


def _parse_date(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        return parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _extract_body(message: Message, content_type: str) -> str | None:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == content_type:
                return _part_text(part)
        return None
    if message.get_content_type() == content_type:
        return _part_text(message)
    return None


def _part_text(part: Message) -> str | None:
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True)
        if payload is None:
            return None
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    if not isinstance(content, str):
        return None
    return content if content != "" else None
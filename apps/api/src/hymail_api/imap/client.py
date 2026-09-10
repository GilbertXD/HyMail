import contextlib
import re
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aioimaplib

from hymail_api.imap.dto import FetchedMessage, FolderSelection, RemoteFolder
from hymail_api.imap.errors import (
    ImapAuthenticationError,
    ImapConnectionError,
    ImapError,
    ImapFetchInterruptedError,
    ImapProtocolError,
    ImapRateLimitError,
)
from hymail_api.imap.parser import parse_message

_FETCH_START_RE = re.compile(rb"(?:\* )?\d+ FETCH \(")
_LITERAL_SIZE_RE = re.compile(rb"\{(\d+)\}$")


class ImapClient:
    def __init__(
        self,
        *,
        host: str,
        username: str,
        password: str,
        port: int = 993,
        ssl: bool = True,
        timeout: float = 30.0,
        client_id: dict[str, str] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._ssl = ssl
        self._username = username
        self._password = password
        self._timeout = timeout
        self._client_id = client_id
        self._client: Any | None = None

    async def connect(self) -> None:
        if self._client is not None:
            return

        client_class = aioimaplib.IMAP4_SSL if self._ssl else aioimaplib.IMAP4
        client = client_class(
            host=self._host,
            port=self._port,
            timeout=self._timeout,
        )
        try:
            await client.wait_hello_from_server()
            response = await client.login(self._username, self._password)
            self._ensure_response_ok(response, "login")
        except Exception as exc:
            with contextlib.suppress(Exception):
                await client.logout()
            raise self._map_exception(exc, "connect") from exc

        self._client = client
        if self._client_id:
            await self._send_client_id()

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        with contextlib.suppress(Exception):
            await client.logout()

    async def capabilities(self) -> set[str]:
        client = self._require_client()
        try:
            await client.capability()
        except Exception as exc:
            raise self._map_exception(exc, "capability") from exc

        raw_capabilities = getattr(client, "capabilities", set())
        result: set[str] = set()
        for capability in raw_capabilities:
            text = (
                capability.decode("utf-8", errors="replace")
                if isinstance(capability, bytes)
                else str(capability)
            )
            text = text.upper()
            if text and text not in {"*", "CAPABILITY"}:
                result.add(text)
        return result

    async def list_folders(self) -> list[RemoteFolder]:
        client = self._require_client()
        try:
            response = await client.list('""', '"*"')
        except Exception as exc:
            raise self._map_exception(exc, "list") from exc
        self._ensure_response_ok(response, "list")

        folders: list[RemoteFolder] = []
        for line in response.lines:
            folder = self._parse_list_line(line)
            if folder is not None:
                folders.append(folder)
        return folders

    async def select_folder(self, folder: str) -> FolderSelection:
        client = self._require_client()
        mailbox = _quote_mailbox(folder)
        try:
            response = await client.select(mailbox)
        except Exception as exc:
            raise self._map_exception(exc, "select") from exc
        self._ensure_response_ok(response, "select")
        return self._parse_select_response(folder, response)

    async def fetch_messages(
        self,
        folder: str,
        start_uid: int,
        end_uid: int | None = None,
        *,
        batch_size: int = 50,
        include_body: bool = True,
    ) -> AsyncIterator[FetchedMessage]:
        if start_uid < 1:
            raise ValueError("start_uid must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        selection = await self.select_folder(folder)
        if end_uid is None and selection.uidnext is not None:
            end_uid = selection.uidnext - 1

        current = start_uid
        while end_uid is None or current <= end_uid:
            if end_uid is None:
                uid_set = f"{current}:*"
            else:
                batch_end = min(current + batch_size - 1, end_uid)
                uid_set = f"{current}:{batch_end}"

            response = await self._fetch(uid_set, include_body=include_body)
            self._ensure_response_ok(response, "fetch")
            fetched = list(self._parse_fetch_response(response))

            if not fetched:
                break
            for message in fetched:
                yield message

            highest_uid = max(message.uid for message in fetched)
            current = highest_uid + 1
            if end_uid is None and len(fetched) < batch_size:
                continue

    async def _fetch(self, uid_set: str, *, include_body: bool) -> Any:
        client = self._require_client()
        parts = (
            "(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[])"
            if include_body
            else "(UID FLAGS INTERNALDATE RFC822.SIZE)"
        )
        try:
            return await client.uid("FETCH", uid_set, parts)
        except Exception as exc:
            raise self._map_exception(exc, "fetch") from exc

    async def _send_client_id(self) -> None:
        if self._client is None or not self._client_id:
            return
        capabilities = await self.capabilities()
        if "ID" not in capabilities:
            return
        try:
            await self._client.id(**self._client_id)
        except Exception as exc:
            raise self._map_exception(exc, "id") from exc

    def _require_client(self) -> Any:
        if self._client is None:
            raise ImapConnectionError("IMAP client is not connected")
        return self._client

    @staticmethod
    def _ensure_response_ok(response: Any, operation: str) -> None:
        result = getattr(response, "result", "OK")
        if result == "OK":
            return

        lines = getattr(response, "lines", []) or []
        message = " ".join(
            line.decode("utf-8", errors="replace")
            if isinstance(line, bytes)
            else str(line)
            for line in lines
        ).strip()
        lowered = message.lower()
        if result == "NO" and any(
            token in lowered
            for token in ("limit", "rate", "too many", "throttl")
        ):
            raise ImapRateLimitError(message or f"{operation} failed")
        if operation in {"login", "connect"}:
            raise ImapAuthenticationError(message or "authentication failed")
        raise ImapProtocolError(message or f"{operation} failed")

    @staticmethod
    def _map_exception(exc: BaseException, operation: str) -> ImapError:
        if isinstance(exc, ImapError):
            return exc
        message = str(exc) or exc.__class__.__name__
        lowered = message.lower()
        if any(token in lowered for token in ("limit", "rate", "too many")):
            return ImapRateLimitError(message)
        if isinstance(exc, aioimaplib.IncompleteRead):
            if operation == "fetch":
                return ImapFetchInterruptedError(message)
            return ImapConnectionError(message)
        if isinstance(exc, aioimaplib.CommandTimeout):
            if operation == "fetch":
                return ImapFetchInterruptedError(message)
            return ImapConnectionError(message)
        if operation in {"connect", "login"} and isinstance(
            exc,
            (aioimaplib.Abort, aioimaplib.Error),
        ):
            return ImapAuthenticationError(message)
        if isinstance(
            exc,
            (
                aioimaplib.Abort,
                aioimaplib.Error,
                ConnectionError,
                OSError,
                TimeoutError,
            ),
        ):
            return ImapConnectionError(message)
        return ImapProtocolError(message)

    @staticmethod
    def _parse_list_line(line: bytes) -> RemoteFolder | None:
        text = line.decode("utf-8", errors="replace").strip()
        if text.startswith("* "):
            text = text[2:]
        if text.upper().startswith("LIST "):
            text = text[5:].lstrip()

        match = re.match(
            r'\((?P<flags>[^)]*)\) (?P<delimiter>NIL|"[^"]*") (?P<name>.+)$',
            text,
            re.IGNORECASE,
        )
        if match is None:
            return None

        flags = frozenset(
            flag for flag in match.group("flags").split() if flag
        )
        delimiter_text = match.group("delimiter")
        delimiter = (
            None if delimiter_text.upper() == "NIL" else _unquote(delimiter_text)
        )
        name = _unquote(match.group("name").strip())
        return RemoteFolder(name=name, delimiter=delimiter, flags=flags)

    @staticmethod
    def _parse_select_response(
        folder: str,
        response: Any,
    ) -> FolderSelection:
        exists = 0
        uidvalidity: int | None = None
        uidnext: int | None = None
        flags: frozenset[str] = frozenset()

        for line in response.lines:
            text = (
                line.decode("utf-8", errors="replace")
                if isinstance(line, bytes)
                else str(line)
            )
            match = re.search(r"(\d+) EXISTS", text, re.IGNORECASE)
            if match:
                exists = int(match.group(1))
            match = re.search(r"\[UIDVALIDITY (\d+)\]", text, re.IGNORECASE)
            if match:
                uidvalidity = int(match.group(1))
            match = re.search(r"\[UIDNEXT (\d+)\]", text, re.IGNORECASE)
            if match:
                uidnext = int(match.group(1))
            match = re.search(r"FLAGS \(([^)]*)\)", text, re.IGNORECASE)
            if match:
                flags = frozenset(
                    flag for flag in match.group(1).split() if flag
                )

        return FolderSelection(
            name=folder,
            exists=exists,
            uidvalidity=uidvalidity,
            uidnext=uidnext,
            flags=flags,
        )

    @staticmethod
    def _parse_fetch_response(response: Any) -> Iterator[FetchedMessage]:
        lines = list(response.lines)
        index = 0
        while index < len(lines):
            start_line = lines[index]
            if not isinstance(start_line, bytes) or not _FETCH_START_RE.match(
                start_line
            ):
                index += 1
                continue

            raw_message = b""
            literal_match = _LITERAL_SIZE_RE.search(start_line)
            if literal_match is not None:
                if index + 1 < len(lines) and isinstance(
                    lines[index + 1],
                    (bytes, bytearray, memoryview),
                ):
                    raw_message = bytes(lines[index + 1])
                index += 2
                if index < len(lines) and _strip_line(lines[index]) == b")":
                    index += 1
            else:
                index += 1

            uid = _match_int(start_line, rb"UID (\d+)")
            if uid is None:
                continue

            parsed = parse_message(raw_message) if raw_message else parse_message(b"")
            yield FetchedMessage(
                uid=uid,
                flags=_match_flags(start_line),
                internal_date=_match_internal_date(start_line),
                size=_match_int(start_line, rb"RFC822\.SIZE (\d+)"),
                raw_message=raw_message,
                parsed=parsed,
            )


def _quote_mailbox(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _match_int(line: bytes, pattern: bytes) -> int | None:
    match = re.search(pattern, line, re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1))


def _match_flags(line: bytes) -> frozenset[str]:
    match = re.search(rb"FLAGS \(([^)]*)\)", line, re.IGNORECASE)
    if match is None:
        return frozenset()
    return frozenset(
        flag.decode("utf-8", errors="replace")
        for flag in match.group(1).split()
        if flag
    )


def _match_internal_date(line: bytes) -> datetime | None:
    match = re.search(rb'INTERNALDATE "([^"]+)"', line, re.IGNORECASE)
    if match is None:
        return None
    try:
        return parsedate_to_datetime(match.group(1).decode("ascii"))
    except (TypeError, ValueError, OverflowError):
        return None


def _strip_line(line: object) -> bytes:
    if isinstance(line, bytes):
        return line.strip()
    return str(line).strip().encode()
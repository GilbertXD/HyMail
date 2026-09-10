import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hymail_api.imap.utf7 import decode_mailbox, encode_mailbox

CRLF = b"\r\n"


@dataclass(slots=True)
class MockMessage:
    uid: int
    raw: bytes
    flags: list[str] = field(default_factory=list)
    internal_date: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class MockImapScenario:
    username: str = "user@example.com"
    password: str = "secret"
    uidvalidity: int = 1
    auth_failures: int = 0
    disconnect_after_commands: int | None = None
    disconnect_on_fetch: bool = False
    rate_limit_after_commands: int | None = None
    command_delay: float = 0.0


class MockImapServer:
    def __init__(self, scenario: MockImapScenario | None = None) -> None:
        self.scenario = scenario or MockImapScenario()
        self._server: asyncio.Server | None = None
        self._port: int | None = None
        self.folders: dict[str, list[MockMessage]] = {"INBOX": [], "Sent": []}
        self._uidnext = 1
        self._connections: set[asyncio.StreamWriter] = set()

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("server is not started")
        return self._port

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._server = await asyncio.start_server(self._handle_client, host, port)
        sockets = self._server.sockets or []
        self._port = sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in list(self._connections):
            writer.close()
        self._connections.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._port = None

    def add_message(
        self,
        raw: bytes,
        *,
        mailbox: str = "INBOX",
        flags: list[str] | None = None,
        uid: int | None = None,
    ) -> int:
        if uid is None:
            uid = self._uidnext
            self._uidnext += 1
        else:
            self._uidnext = max(self._uidnext, uid + 1)
        self.folders.setdefault(mailbox, []).append(
            MockMessage(uid=uid, raw=raw, flags=flags or [])
        )
        return uid

    def set_uidvalidity(self, value: int) -> None:
        self.scenario.uidvalidity = value

    def clear_mailbox(self, mailbox: str = "INBOX") -> None:
        self.folders[mailbox] = []

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._connections.add(writer)
        command_count = 0
        selected_mailbox: str | None = None
        fetch_disconnected = False

        try:
            writer.write(b"* OK [CAPABILITY IMAP4rev1 ID] HyMail mock ready\r\n")
            await writer.drain()

            while True:
                line = await reader.readline()
                if not line:
                    break

                command_count += 1
                if self.scenario.command_delay:
                    await asyncio.sleep(self.scenario.command_delay)

                if self._should_disconnect(command_count):
                    await self._close_writer(writer)
                    return

                if self._should_rate_limit(command_count):
                    tag = self._tag(line)
                    await self._write_line(
                        writer,
                        f"{tag} NO [LIMIT] Too many requests".encode(),
                    )
                    continue

                tag, command, args = self._parse_command(line)
                if not tag or not command:
                    continue

                upper = command.upper()
                if upper == "CAPABILITY":
                    await self._write_line(
                        writer,
                        b"* CAPABILITY IMAP4rev1 ID UIDPLUS",
                    )
                    await self._write_ok(writer, tag, "CAPABILITY completed")
                elif upper == "LOGIN":
                    if self.scenario.auth_failures > 0:
                        self.scenario.auth_failures -= 1
                        await self._write_no(
                            writer,
                            tag,
                            "AUTHENTICATIONFAILED",
                        )
                        continue
                    username, password = self._parse_login_args(args)
                    if (
                        username != self.scenario.username
                        or password != self.scenario.password
                    ):
                        await self._write_no(
                            writer,
                            tag,
                            "AUTHENTICATIONFAILED",
                        )
                        continue
                    await self._write_ok(writer, tag, "LOGIN completed")
                elif upper == "ID":
                    await self._write_line(
                        writer,
                        b'* ID ("name" "HyMail Mock")',
                    )
                    await self._write_ok(writer, tag, "ID completed")
                elif upper in {"LIST", "LSUB"}:
                    await self._handle_list(writer, tag, args)
                elif upper in {"SELECT", "EXAMINE"}:
                    selected_mailbox = self._parse_mailbox(args)
                    await self._handle_select(
                        writer,
                        tag,
                        selected_mailbox,
                        readonly=upper == "EXAMINE",
                    )
                elif upper == "UID":
                    subcommand, rest = self._parse_uid_args(args)
                    if subcommand == "FETCH" and selected_mailbox:
                        if self.scenario.disconnect_on_fetch and not fetch_disconnected:
                            fetch_disconnected = True
                            await self._handle_fetch(
                                writer,
                                tag,
                                rest,
                                selected_mailbox,
                                disconnect=True,
                            )
                            return
                        await self._handle_fetch(
                            writer,
                            tag,
                            rest,
                            selected_mailbox,
                            disconnect=False,
                        )
                    else:
                        await self._write_no(
                            writer,
                            tag,
                            "UID command not supported",
                        )
                elif upper == "NOOP":
                    await self._write_ok(writer, tag, "NOOP completed")
                elif upper == "LOGOUT":
                    await self._write_line(writer, b"* BYE Logging out")
                    await self._write_ok(writer, tag, "LOGOUT completed")
                    break
                else:
                    await self._write_bad(
                        writer,
                        tag,
                        f"Unknown command {command}",
                    )
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._connections.discard(writer)
            await self._close_writer(writer)

    def _should_disconnect(self, command_count: int) -> bool:
        limit = self.scenario.disconnect_after_commands
        return limit is not None and command_count >= limit

    def _should_rate_limit(self, command_count: int) -> bool:
        limit = self.scenario.rate_limit_after_commands
        return limit is not None and command_count >= limit

    async def _handle_list(
        self,
        writer: asyncio.StreamWriter,
        tag: str,
        args: str,
    ) -> None:
        for name in sorted(self.folders):
            # Mailboxes live here in decoded form; the wire carries the
            # modified UTF-7 form, exactly as a real server does.
            await self._write_line(
                writer,
                f'* LIST (\\HasNoChildren) "/" "{encode_mailbox(name)}"'.encode(),
            )
        await self._write_ok(writer, tag, "LIST completed")

    async def _handle_select(
        self,
        writer: asyncio.StreamWriter,
        tag: str,
        mailbox: str,
        *,
        readonly: bool,
    ) -> None:
        messages = self.folders.get(mailbox)
        if messages is None:
            await self._write_no(writer, tag, "MAILBOX_NOT_FOUND")
            return

        uidnext = max(self._uidnext, max((m.uid for m in messages), default=0) + 1)
        await self._write_line(
            writer,
            b"* FLAGS (\\Answered \\Flagged \\Deleted \\Seen \\Draft)",
        )
        await self._write_line(writer, f"* {len(messages)} EXISTS".encode())
        await self._write_line(writer, b"* 0 RECENT")
        await self._write_line(
            writer,
            f"* OK [UIDVALIDITY {self.scenario.uidvalidity}] UIDs valid".encode(),
        )
        await self._write_line(
            writer,
            f"* OK [UIDNEXT {uidnext}] Predicted next UID".encode(),
        )
        mode = "READ-ONLY" if readonly else "READ-WRITE"
        await self._write_ok(writer, tag, f"[{mode}] SELECT completed")

    async def _handle_fetch(
        self,
        writer: asyncio.StreamWriter,
        tag: str,
        rest: str,
        mailbox: str,
        *,
        disconnect: bool,
    ) -> None:
        set_part, _, parts_raw = rest.partition(" ")
        start, end = self._parse_sequence_set(set_part)
        include_body = any(
            token in parts_raw
            for token in ("BODY.PEEK[]", "BODY[]", "RFC822")
        )
        include_header = any(
            token in parts_raw
            for token in ("BODY.PEEK[HEADER]", "BODY[HEADER]", "RFC822.HEADER")
        )

        for sequence, message in enumerate(self.folders.get(mailbox, []), start=1):
            if not (start <= message.uid <= end):
                continue
            payload = message.raw if include_body else b""
            if include_header and not include_body:
                payload = _header_bytes(message.raw)
            if disconnect:
                await self._write_line(
                    writer,
                    (
                        f"* {sequence} FETCH (UID {message.uid} "
                        f"FLAGS ({' '.join(message.flags)}) "
                        f"INTERNALDATE \"{message.internal_date:%d-%b-%Y %H:%M:%S %z}\" "
                        f"RFC822.SIZE {len(message.raw)} BODY[] {{{len(payload)}}}"
                    ).encode(),
                    drain=False,
                )
                await writer.drain()
                await asyncio.sleep(0)
                await self._close_writer(writer)
                return
            await self._send_fetch_message(
                writer,
                sequence,
                message,
                payload,
            )
        await self._write_ok(writer, tag, "FETCH completed")

    async def _send_fetch_message(
        self,
        writer: asyncio.StreamWriter,
        sequence: int,
        message: MockMessage,
        payload: bytes,
    ) -> None:
        attrs = (
            f"* {sequence} FETCH (UID {message.uid} "
            f"FLAGS ({' '.join(message.flags)}) "
            f"INTERNALDATE \"{message.internal_date:%d-%b-%Y %H:%M:%S %z}\" "
            f"RFC822.SIZE {len(message.raw)}"
        )
        if payload:
            attrs += f" BODY[] {{{len(payload)}}}"
        writer.write(attrs.encode() + CRLF + payload + b")" + CRLF)
        await writer.drain()

    @staticmethod
    def _parse_command(line: bytes) -> tuple[str | None, str | None, str]:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return None, None, ""
        parts = text.split(" ", 2)
        if len(parts) < 2:
            return None, None, ""
        return parts[0], parts[1], parts[2] if len(parts) > 2 else ""

    @staticmethod
    def _tag(line: bytes) -> str:
        return line.decode("utf-8", errors="replace").strip().split(" ", 1)[0]

    @staticmethod
    def _parse_login_args(args: str) -> tuple[str, str]:
        text = args.strip()
        parts = text.split(" ", 1)
        if len(parts) < 2:
            return "", ""
        username = parts[0].strip('"')
        password = parts[1].strip().strip('"')
        return username, password

    @staticmethod
    def _parse_mailbox(args: str) -> str:
        text = args.strip()
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return decode_mailbox(text)

    @staticmethod
    def _parse_uid_args(args: str) -> tuple[str, str]:
        parts = args.strip().split(" ", 1)
        if len(parts) < 2:
            return parts[0].upper(), ""
        return parts[0].upper(), parts[1]

    @staticmethod
    def _parse_sequence_set(value: str) -> tuple[int, int]:
        if ":" not in value:
            uid = int(value)
            return uid, uid
        start_text, end_text = value.split(":", 1)
        start = int(start_text)
        end = 2**31 - 1 if end_text == "*" else int(end_text)
        return start, end

    async def _write_line(
        self,
        writer: asyncio.StreamWriter,
        line: bytes,
        *,
        drain: bool = True,
    ) -> None:
        writer.write(line + CRLF)
        if drain:
            await writer.drain()

    async def _write_ok(
        self,
        writer: asyncio.StreamWriter,
        tag: str,
        text: str,
    ) -> None:
        await self._write_line(writer, f"{tag} OK {text}".encode())

    async def _write_no(
        self,
        writer: asyncio.StreamWriter,
        tag: str,
        text: str,
    ) -> None:
        await self._write_line(writer, f"{tag} NO {text}".encode())

    async def _write_bad(
        self,
        writer: asyncio.StreamWriter,
        tag: str,
        text: str,
    ) -> None:
        await self._write_line(writer, f"{tag} BAD {text}".encode())

    @staticmethod
    async def _close_writer(writer: asyncio.StreamWriter) -> None:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _header_bytes(raw: bytes) -> bytes:
    head, separator, _ = raw.partition(b"\r\n\r\n")
    return head + separator if separator else head
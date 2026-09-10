"""IMAP modified UTF-7 mailbox name codec (RFC 3501 section 5.1.3).

IMAP speaks 7-bit ASCII on the wire, so non-ASCII mailbox names are shifted
into a modified BASE64 of UTF-16BE delimited by ``&`` and ``-``:

    "已删除"  <->  "&XfJSIJZk-"

Printable ASCII stands for itself, except ``&`` which becomes ``&-``. Compared
with plain BASE64 the alphabet uses ``,`` instead of ``/`` and the padding is
dropped.

Both directions live here because they must agree: a client that decodes LIST
responses but forgets to re-encode SELECT would ask the server for a mailbox
that does not exist.
"""

from __future__ import annotations

import base64
import binascii

__all__ = ["decode_mailbox", "encode_mailbox"]


def encode_mailbox(name: str) -> str:
    """Encode a mailbox name for transmission to an IMAP server."""
    if not name:
        return name

    chunks: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        raw = "".join(pending).encode("utf-16-be")
        payload = base64.b64encode(raw).decode("ascii").rstrip("=")
        chunks.append("&" + payload.replace("/", ",") + "-")
        pending.clear()

    for char in name:
        if char == "&":
            flush()
            chunks.append("&-")
        elif "\x20" <= char <= "\x7e":
            flush()
            chunks.append(char)
        else:
            pending.append(char)

    flush()
    return "".join(chunks)


def decode_mailbox(name: str) -> str:
    """Decode a mailbox name received from an IMAP server.

    Malformed input is passed through verbatim rather than raising: a server
    sending something unexpected must not take the whole folder listing down.
    """
    if "&" not in name:
        return name

    decoded: list[str] = []
    index = 0
    length = len(name)

    while index < length:
        char = name[index]
        if char != "&":
            decoded.append(char)
            index += 1
            continue

        end = name.find("-", index + 1)
        if end == -1:
            # Unterminated shift sequence; keep the remainder untouched.
            decoded.append(name[index:])
            break

        decoded.append(_decode_shifted(name[index + 1 : end]))
        index = end + 1

    return "".join(decoded)


def _decode_shifted(payload: str) -> str:
    if not payload:
        # "&-" is the escape for a literal ampersand.
        return "&"

    padded = payload.replace(",", "/")
    padded += "=" * (-len(padded) % 4)

    try:
        raw = base64.b64decode(padded, validate=True)
        return raw.decode("utf-16-be")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return "&" + payload + "-"

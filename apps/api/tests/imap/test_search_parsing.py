"""Parsing of UID SEARCH responses.

aioimaplib hands back the untagged payload without its ``* SEARCH`` prefix and
appends the tagged trailer to the same list, so the parser has to cope with
both shapes. These tests pin that down.
"""

import pytest

from hymail_api.imap.client import _parse_search_line


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # What aioimaplib actually produces today.
        (b"1 2 3", [1, 2, 3]),
        (b"42", [42]),
        # The raw wire form, in case the library starts passing it through.
        (b"* SEARCH 1 2 3", [1, 2, 3]),
        (b"* SEARCH", []),
        # The tagged trailer that shares the list.
        (b"SEARCH completed", []),
        (b"SEARCH", []),
        # An empty mailbox.
        (b"", []),
        (b"   ", []),
    ],
)
def test_parse_search_line(line: bytes, expected: list[int]) -> None:
    assert _parse_search_line(line) == expected


def test_parse_search_line_accepts_text() -> None:
    assert _parse_search_line("7 8") == [7, 8]


def test_parse_search_line_rejects_non_numeric_payloads() -> None:
    # Guards against treating a chattering server as a list of UIDs.
    assert _parse_search_line(b"NO [LIMIT] Too many requests") == []
    assert _parse_search_line(b"1 two 3") == []

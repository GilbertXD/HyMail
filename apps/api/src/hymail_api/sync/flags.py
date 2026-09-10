"""Mapping between IMAP flags and the local read/starred columns.

The columns exist so the UI can filter without unpacking ``flags_json`` on
every row; this module is the single place that decides what they mean.
"""

from collections.abc import Iterable

SEEN = "\\Seen"
FLAGGED = "\\Flagged"

_SEEN = SEEN.lower()
_FLAGGED = FLAGGED.lower()


def flags_to_state(flags: Iterable[str]) -> tuple[bool, bool]:
    """Return ``(is_read, is_starred)`` for a set of IMAP flags.

    Flag names are case-insensitive on the wire, so they are compared lowered.
    """
    lowered = {flag.lower() for flag in flags}
    return _SEEN in lowered, _FLAGGED in lowered


def read_toggle_flags(is_read: bool) -> tuple[tuple[str, ...], bool]:
    """Return ``(flags, add)`` for writing a read/unread change."""
    return (SEEN,), is_read


def star_toggle_flags(is_starred: bool) -> tuple[tuple[str, ...], bool]:
    """Return ``(flags, add)`` for writing a star/unstar change."""
    return (FLAGGED,), is_starred

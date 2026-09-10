class ImapError(Exception):
    """Base class for IMAP adapter errors."""


class ImapAuthenticationError(ImapError):
    """The server rejected authentication."""


class ImapConnectionError(ImapError):
    """The connection was lost or could not be established."""


class ImapProtocolError(ImapError):
    """The server returned an unexpected protocol response."""


class ImapRateLimitError(ImapError):
    """The server asked us to slow down."""


class ImapFetchInterruptedError(ImapConnectionError):
    """A FETCH operation was interrupted before completion."""


class ImapFolderNotFoundError(ImapError):
    """The requested mailbox does not exist on the server.

    Permanent: retrying will not help, so the queue fails the job outright
    instead of burning its attempts.
    """
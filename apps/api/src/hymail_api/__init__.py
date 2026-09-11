"""HyMail API package."""

from hymail_api.core.config import settings

# Derived rather than repeated: the version surfaces through settings (health,
# OpenAPI), so a second literal here would only be able to drift.
__version__ = settings.version

import asyncio
import contextlib
import os
import tempfile
from email.mime.text import MIMEText
from pathlib import Path

import uvicorn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hymail_api.db.models  # noqa: F401
from hymail_api.api.security import DEFAULT_ALLOWED_ORIGINS
from hymail_api.db.base import Base
from hymail_api.db.session import create_engine
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapScenario, MockImapServer
from hymail_api.main import create_app

API_PORT = int(os.environ.get("HYMAIL_E2E_API_PORT", "8000"))
IMAP_PORT = int(os.environ.get("HYMAIL_E2E_IMAP_PORT", "11430"))
WEB_PORT = int(os.environ.get("HYMAIL_E2E_WEB_PORT", "5173"))
USERNAME = "user@example.com"
PASSWORD = "secret"

# The Origin allow-list is port-specific, so a non-default web port has to be
# added or every API call from the page would be rejected.
ALLOWED_ORIGINS = [
    *DEFAULT_ALLOWED_ORIGINS,
    f"http://127.0.0.1:{WEB_PORT}",
    f"http://localhost:{WEB_PORT}",
]


def make_raw_message(subject: str, body: str) -> bytes:
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    message["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
    return message.as_bytes()


def make_html_message(subject: str) -> bytes:
    """An email that tries to restyle the whole document.

    Real marketing mail ships exactly this kind of rule, which is what made
    the app's own font change whenever an HTML message was opened.
    """
    message = MIMEText(
        "<html><head>"
        '<style>html,body{font-family:"Comic Sans MS"}</style>'
        "</head><body><p>rendered html body</p></body></html>",
        "html",
        "utf-8",
    )
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    message["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
    return message.as_bytes()


async def main() -> None:
    db_path = Path(tempfile.gettempdir()) / "hymail-e2e.db"
    if db_path.exists():
        db_path.unlink()

    engine = create_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    mock_server = MockImapServer(
        MockImapScenario(username=USERNAME, password=PASSWORD)
    )
    await mock_server.start(host="127.0.0.1", port=IMAP_PORT)
    mock_server.add_message(make_raw_message("E2E One", "hello e2e"), uid=1)
    mock_server.add_message(make_raw_message("E2E Two", "second"), uid=2)
    mock_server.add_message(make_html_message("E2E HTML"), uid=3)
    # A second mailbox with mail, so "sync all" has more than one job.
    mock_server.add_message(
        make_raw_message("E2E Sent", "sent body"),
        mailbox="Sent",
        uid=1,
    )

    def client_factory(_account) -> ImapClient:
        return ImapClient(
            host="127.0.0.1",
            port=IMAP_PORT,
            ssl=False,
            username=USERNAME,
            password=PASSWORD,
            timeout=5.0,
        )

    app = create_app(
        session_factory=session_factory,
        imap_client_factory=client_factory,
        allowed_origins=ALLOWED_ORIGINS,
    )

    # Test-only control surface. Defined here rather than in the app so it can
    # never ship: it lets a browser test delete a message server-side and then
    # observe reconciliation noticing.
    @app.post("/__e2e/messages/remove")
    async def _remove_message(payload: dict[str, object]) -> dict[str, bool]:
        removed = mock_server.remove_message(
            int(payload["uid"]),  # type: ignore[arg-type]
            mailbox=str(payload.get("mailbox", "INBOX")),
        )
        return {"removed": removed}
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=API_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        await mock_server.stop()
        await engine.dispose()
        with contextlib.suppress(OSError):
            db_path.unlink()


if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import contextlib
import os
import tempfile
from email.mime.text import MIMEText
from pathlib import Path

import uvicorn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hymail_api.db.models  # noqa: F401
from hymail_api.db.base import Base
from hymail_api.db.session import create_engine
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapScenario, MockImapServer
from hymail_api.main import create_app

API_PORT = int(os.environ.get("HYMAIL_E2E_API_PORT", "8000"))
IMAP_PORT = int(os.environ.get("HYMAIL_E2E_IMAP_PORT", "11430"))
USERNAME = "user@example.com"
PASSWORD = "secret"


def make_raw_message(subject: str, body: str) -> bytes:
    message = MIMEText(body, "plain", "utf-8")
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
    )
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
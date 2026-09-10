import argparse
import asyncio
import contextlib
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

USERNAME = "user@example.com"
PASSWORD = "secret"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HyMail demo server")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--imap-port", type=int, default=11430)
    parser.add_argument("--messages", type=int, default=20)
    parser.add_argument("--uidvalidity", type=int, default=1)
    parser.add_argument("--auth-failures", type=int, default=0)
    parser.add_argument("--disconnect-on-fetch", action="store_true")
    parser.add_argument("--rate-limit-after-commands", type=int, default=None)
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def make_raw_message(index: int) -> bytes:
    message = MIMEText(
        f"HyMail demo message {index}\n\nhello from mock imap",
        "plain",
        "utf-8",
    )
    message["Subject"] = f"Demo {index:04d}"
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Bob <bob@example.com>"
    message["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
    return message.as_bytes()


async def main() -> None:
    args = parse_args()
    default_db = Path(tempfile.gettempdir()) / "hymail-demo.db"
    db_path = Path(args.db) if args.db else default_db

    if args.reset and db_path.exists():
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

    scenario = MockImapScenario(
        username=USERNAME,
        password=PASSWORD,
        uidvalidity=args.uidvalidity,
        auth_failures=args.auth_failures,
        disconnect_on_fetch=args.disconnect_on_fetch,
        rate_limit_after_commands=args.rate_limit_after_commands,
    )
    mock_server = MockImapServer(scenario)
    await mock_server.start(host="127.0.0.1", port=args.imap_port)

    for index in range(1, args.messages + 1):
        mock_server.add_message(make_raw_message(index), uid=index)

    def client_factory(_account) -> ImapClient:
        return ImapClient(
            host="127.0.0.1",
            port=args.imap_port,
            ssl=False,
            username=USERNAME,
            password=PASSWORD,
            timeout=5.0,
        )

    app = create_app(
        session_factory=session_factory,
        imap_client_factory=client_factory,
    )

    print("HyMail demo server")
    print(f"  API:      http://127.0.0.1:{args.api_port}")
    print(f"  IMAP:     127.0.0.1:{args.imap_port}")
    print(f"  username: {USERNAME}")
    print(f"  password: {PASSWORD}")
    print("  ssl:      false")
    print(f"  database: {db_path}")
    print(f"  messages: {args.messages}")
    print()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=args.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        with contextlib.suppress(BaseException):
            await mock_server.stop()
        with contextlib.suppress(BaseException):
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
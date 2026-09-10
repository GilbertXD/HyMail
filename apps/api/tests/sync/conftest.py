from collections.abc import AsyncIterator, Callable
from email.mime.text import MIMEText
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hymail_api.db.models  # noqa: F401
from hymail_api.db.base import Base
from hymail_api.db.models.account import Account
from hymail_api.db.session import create_engine
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapScenario, MockImapServer


@pytest_asyncio.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path / "sync-test.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def account_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    async with session_factory() as session:
        account = Account(
            email=f"{uuid4()}@example.com",
            provider="163",
            imap_ssl=True,
            username="user@example.com",
            status="active",
        )
        session.add(account)
        await session.commit()
        return account.id


@pytest_asyncio.fixture
async def mock_server() -> AsyncIterator[MockImapServer]:
    server = MockImapServer(
        MockImapScenario(username="user@example.com", password="secret")
    )
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def imap_client_factory(
    mock_server: MockImapServer,
) -> Callable[[], ImapClient]:
    def factory() -> ImapClient:
        return ImapClient(
            host="127.0.0.1",
            port=mock_server.port,
            ssl=False,
            username="user@example.com",
            password="secret",
            timeout=1.0,
        )

    return factory


@pytest.fixture
def message_factory() -> Callable[[str, str], bytes]:
    def make(subject: str, body: str = "hello") -> bytes:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = "Alice <alice@example.com>"
        message["To"] = "Bob <bob@example.com>"
        message["Message-ID"] = f"<{subject}@example.com>"
        message["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
        return message.as_bytes()

    return make
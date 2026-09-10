from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hymail_api.db.models  # noqa: F401
import hymail_api.services.accounts as accounts
from hymail_api.db.base import Base
from hymail_api.db.session import create_engine
from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapScenario, MockImapServer
from hymail_api.main import create_app
from hymail_api.services.outbox import OutboxDispatcher
from hymail_api.services.sync_scheduler import SyncScheduler


@pytest_asyncio.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path / "api-test.db"
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
async def mock_server() -> AsyncIterator[MockImapServer]:
    server = MockImapServer(
        MockImapScenario(username="user@example.com", password="secret")
    )
    await server.start()
    yield server
    await server.stop()


@pytest.fixture(autouse=True)
def fake_dpapi(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_protect(secret: str) -> bytes:
        return b"fake:" + secret.encode("utf-8")

    def fake_unprotect(blob: bytes) -> str:
        return blob.decode("utf-8").removeprefix("fake:")

    monkeypatch.setattr(accounts, "protect_secret", fake_protect)
    monkeypatch.setattr(accounts, "unprotect_secret", fake_unprotect)


@pytest_asyncio.fixture
async def app(session_factory, mock_server) -> AsyncIterator[FastAPI]:
    def client_factory(_account) -> ImapClient:
        return ImapClient(
            host="127.0.0.1",
            port=mock_server.port,
            ssl=False,
            username="user@example.com",
            password="secret",
            timeout=1.0,
        )

    application = create_app(
        session_factory=session_factory,
        imap_client_factory=client_factory,
        # Keeps queue tests fast without changing the shipped defaults.
        scheduler=SyncScheduler(
            session_factory=session_factory,
            client_factory=client_factory,
            backoff_base_seconds=0.0,
            max_backoff_seconds=0.0,
            poll_interval=0.01,
        ),
        outbox_dispatcher=OutboxDispatcher(
            session_factory=session_factory,
            client_factory=client_factory,
            backoff_base_seconds=0.0,
            max_backoff_seconds=0.0,
            poll_interval=0.01,
        ),
    )
    yield application
    # ASGITransport does not run lifespan, so the workers have to be stopped
    # explicitly or they outlive the test.
    await application.state.outbox_dispatcher.stop()
    await application.state.sync_scheduler.stop()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.fixture
def account_payload(mock_server: MockImapServer) -> dict[str, object]:
    return {
        "email": "user@example.com",
        "display_name": "Demo",
        "provider": "custom",
        "imap_host": "127.0.0.1",
        "imap_port": mock_server.port,
        "imap_ssl": False,
        "username": "user@example.com",
        "secret": "secret",
    }
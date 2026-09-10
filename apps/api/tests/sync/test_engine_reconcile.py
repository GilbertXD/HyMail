"""Reconciliation: noticing what the server no longer has."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import (
    count_messages,
    get_event_values,
    get_last_reconcile_at,
    get_message_subjects,
    get_missing_flags,
)


def build_engine(
    session_factory: async_sessionmaker[AsyncSession],
    imap_client_factory: Callable[[], ImapClient],
) -> SyncEngine:
    return SyncEngine(
        session_factory=session_factory,
        imap_client_factory=imap_client_factory,
        batch_size=10,
        max_attempts=1,
    )


async def test_reconcile_flags_messages_deleted_on_the_server(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    for uid, subject in enumerate(["One", "Two", "Three"], start=1):
        mock_server.add_message(message_factory(subject), uid=uid)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")
    assert await count_messages(session_factory, account_id, "INBOX") == 3

    mock_server.remove_message(2)

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.newly_missing == 1
    assert result.restored == 0
    assert result.remote_total == 2
    assert result.local_total == 3
    assert result.skipped_mass_flagging is False

    assert await get_missing_flags(session_factory, account_id, "INBOX") == [
        (1, False),
        (2, True),
        (3, False),
    ]

    # The row is kept: the change is explainable rather than silently lost.
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == ["One", "Two", "Three"]

    assert await get_last_reconcile_at(
        session_factory,
        account_id,
        "INBOX",
    ) is not None

    events = await get_event_values(session_factory, account_id)
    assert any(event[0] == "sync.reconcile" for event in events)


async def test_reconcile_clears_the_flag_when_a_message_returns(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """A move between folders, or a server hiccup, must be reversible."""
    for uid, subject in enumerate(["One", "Two"], start=1):
        mock_server.add_message(message_factory(subject), uid=uid)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    removed = mock_server.folders["INBOX"].pop(1)
    first = await engine.reconcile_folder(account_id, "INBOX")
    assert first.newly_missing == 1

    mock_server.folders["INBOX"].insert(1, removed)

    second = await engine.reconcile_folder(account_id, "INBOX")

    assert second.restored == 1
    assert second.newly_missing == 0
    assert await get_missing_flags(session_factory, account_id, "INBOX") == [
        (1, False),
        (2, False),
    ]


async def test_reconcile_also_pulls_new_mail(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    mock_server.add_message(message_factory("One"), uid=1)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.add_message(message_factory("Two"), uid=2)

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.synced_count == 1
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == ["One", "Two"]
    assert await get_missing_flags(session_factory, account_id, "INBOX") == [
        (1, False),
        (2, False),
    ]


async def test_reconcile_skips_an_inconsistent_search_answer(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """SELECT and SEARCH disagreeing must not wipe the mailbox view.

    A server that reports three messages and then lists no UIDs is broken, and
    believing it would mark everything as deleted, which looks exactly like
    data loss.
    """
    for uid in range(1, 4):
        mock_server.add_message(message_factory(f"Msg {uid}"), uid=uid)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.scenario.search_returns_empty = True

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.skipped_mass_flagging is True
    assert result.newly_missing == 0
    assert all(
        not missing
        for _, missing in await get_missing_flags(
            session_factory,
            account_id,
            "INBOX",
        )
    )


async def test_reconcile_flags_a_genuinely_emptied_folder(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """An empty mailbox is a real answer, not a suspicious one.

    This is what distinguishes the safety valve from simply refusing to
    believe deletions: EXISTS agrees with SEARCH, so the folder reconciles.
    """
    for uid in range(1, 4):
        mock_server.add_message(message_factory(f"Msg {uid}"), uid=uid)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.clear_mailbox()

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.skipped_mass_flagging is False
    assert result.newly_missing == 3
    assert all(
        missing
        for _, missing in await get_missing_flags(
            session_factory,
            account_id,
            "INBOX",
        )
    )


async def test_reconcile_survives_a_uidvalidity_change(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """A changed UIDVALIDITY resyncs rather than misreading every UID."""
    mock_server.add_message(message_factory("Old One"), uid=1)
    mock_server.add_message(message_factory("Old Two"), uid=2)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.clear_mailbox()
    mock_server.set_uidvalidity(99)
    mock_server.add_message(message_factory("New One"), uid=1)

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.uidvalidity == 99
    assert await get_message_subjects(
        session_factory,
        account_id,
        "INBOX",
    ) == ["New One"]
    assert await count_messages(session_factory, account_id, "INBOX") == 1

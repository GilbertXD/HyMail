"""Move attribution: connecting a message that vanished to where it went.

A move gives the message a new UID in another mailbox. Without UIDPLUS the
only thread to pull is the Message-ID, which is evidence rather than proof —
so these tests also pin down when the app declines to guess.

Each fixture keeps a second message behind, because a folder emptied entirely
hits the "server says no UIDs" safety valve from M2 and is deliberately not
flagged at all.
"""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hymail_api.imap.client import ImapClient
from hymail_api.imap.mock_server import MockImapServer
from hymail_api.sync.engine import SyncEngine
from tests.sync.helpers import get_missing_flags, get_move_targets


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


def _seed_folder(
    mock_server: MockImapServer,
    message_factory: Callable[[str, str], bytes],
    *,
    subject: str = "Moving",
) -> None:
    """A message that will move, plus a keeper so the folder is never empty."""
    mock_server.add_message(
        message_factory(subject),
        mailbox="INBOX",
        uid=1,
    )
    mock_server.add_message(
        message_factory("Keeper"),
        mailbox="INBOX",
        uid=2,
    )


async def test_move_is_attributed_when_the_destination_is_synced_after(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """The source notices first, so the explanation arrives with the mail."""
    _seed_folder(mock_server, message_factory)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.move_message(1, from_mailbox="INBOX", to_mailbox="Sent")

    # The source reconciles while the destination is still unknown.
    first = await engine.reconcile_folder(account_id, "INBOX")
    assert first.newly_missing == 1
    assert first.moved == 0
    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, None), (2, None)]

    # Fetching the destination is what closes the loop.
    await engine.sync_folder(account_id, "Sent")

    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, "Sent"), (2, None)]


async def test_move_is_attributed_when_the_source_reconciles_after(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """The other order: the destination is known before the source notices."""
    _seed_folder(mock_server, message_factory)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.move_message(1, from_mailbox="INBOX", to_mailbox="Sent")
    await engine.sync_folder(account_id, "Sent")

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.newly_missing == 1
    assert result.moved == 1
    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, "Sent"), (2, None)]
    assert await get_missing_flags(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, True), (2, False)]


async def test_ambiguous_message_id_is_not_attributed(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """A Message-ID can legitimately exist twice; do not guess which one.

    A message you CC yourself lives in both Sent and INBOX with the same
    Message-ID, so a match in two folders proves nothing about where the
    vanished copy went.
    """
    shared = message_factory("Shared id")
    mock_server.add_message(shared, mailbox="INBOX", uid=1)
    mock_server.add_message(
        message_factory("Keeper"),
        mailbox="INBOX",
        uid=2,
    )
    mock_server.add_message(shared, mailbox="Sent", uid=1)
    mock_server.add_message(shared, mailbox="Drafts", uid=1)

    engine = build_engine(session_factory, imap_client_factory)
    for name in ("INBOX", "Sent", "Drafts"):
        await engine.sync_folder(account_id, name)

    mock_server.remove_message(1, mailbox="INBOX")

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.newly_missing == 1
    assert result.moved == 0
    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, None), (2, None)]


async def test_move_attribution_needs_a_message_id(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """Without a Message-ID there is nothing to match on; say nothing."""
    mock_server.add_message(
        b"Subject: No id\r\nFrom: a@example.com\r\n\r\nbody",
        mailbox="INBOX",
        uid=1,
    )
    mock_server.add_message(
        message_factory("Keeper"),
        mailbox="INBOX",
        uid=2,
    )

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.move_message(1, from_mailbox="INBOX", to_mailbox="Sent")
    await engine.sync_folder(account_id, "Sent")

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.moved == 0
    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, None), (2, None)]


async def test_stale_attribution_is_dropped_when_it_stops_holding(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """A message that leaves the destination makes the note wrong.

    It comes back to the original folder under a *new* UID, so the old UID is
    still genuinely gone and stays flagged — but the "it went to Sent" note
    must not survive, because Sent no longer has it.
    """
    _seed_folder(mock_server, message_factory, subject="Boomerang")

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.move_message(1, from_mailbox="INBOX", to_mailbox="Sent")
    await engine.sync_folder(account_id, "Sent")
    await engine.reconcile_folder(account_id, "INBOX")
    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, "Sent"), (2, None)]

    mock_server.move_message(
        mock_server.folders["Sent"][0].uid,
        from_mailbox="Sent",
        to_mailbox="INBOX",
    )
    # A whole-account reconcile touches both folders, which is what makes the
    # stale row in Sent go away.
    await engine.reconcile_folder(account_id, "Sent")
    await engine.sync_folder(account_id, "INBOX")
    await engine.reconcile_folder(account_id, "INBOX")

    # The old UID really is absent from the server, so it stays flagged.
    assert await get_missing_flags(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, True), (2, False), (3, False)]
    # ...but nothing claims to know where it went.
    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, None), (2, None), (3, None)]


async def test_a_moved_out_single_message_is_still_flagged(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    mock_server: MockImapServer,
    imap_client_factory: Callable[[], ImapClient],
    message_factory: Callable[[str, str], bytes],
) -> None:
    """Emptying a folder is a real answer, not a suspicious one.

    The safety valve keys off SELECT's EXISTS, so a mailbox that genuinely
    reports zero still reconciles rather than being written off.
    """
    mock_server.add_message(message_factory("Only"), mailbox="INBOX", uid=1)

    engine = build_engine(session_factory, imap_client_factory)
    await engine.sync_folder(account_id, "INBOX")

    mock_server.move_message(1, from_mailbox="INBOX", to_mailbox="Sent")
    await engine.sync_folder(account_id, "Sent")

    result = await engine.reconcile_folder(account_id, "INBOX")

    assert result.skipped_mass_flagging is False
    assert result.moved == 1
    assert await get_move_targets(
        session_factory,
        account_id,
        "INBOX",
    ) == [(1, "Sent")]

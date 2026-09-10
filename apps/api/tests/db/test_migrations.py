import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

API_DIR = Path(__file__).resolve().parents[2]


def build_alembic_config(database_url: str) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(API_DIR / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migrations_create_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "migration-test.db"
    database_url = f"sqlite:///{db_path.as_posix()}"

    command.upgrade(build_alembic_config(database_url), "head")

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' ORDER BY name"
        ).fetchall()

    table_names = {row[0] for row in rows}
    assert {
        "account",
        "alembic_version",
        "folder",
        "message",
        "outbox_action",
        "sync_cursor",
        "sync_event",
        "sync_job",
    }.issubset(table_names)

    with sqlite3.connect(db_path) as connection:
        message_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(message)")
        }
        job_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sync_job)")
        }
        cursor_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(sync_cursor)")
        }
        outbox_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(outbox_action)")
        }

    assert {"remote_missing", "remote_missing_at"}.issubset(message_columns)
    assert {"is_read", "is_starred"}.issubset(message_columns)
    assert "moved_to_folder_id" in message_columns
    assert "kind" in job_columns
    assert {"last_reconcile_at", "last_flags_reconcile_at"}.issubset(
        cursor_columns
    )
    assert {"type", "state", "payload_json", "lease_expires_at"}.issubset(
        outbox_columns
    )


def test_migration_can_downgrade_to_base(tmp_path: Path) -> None:
    db_path = tmp_path / "downgrade-test.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    config = build_alembic_config(database_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' ORDER BY name"
        ).fetchall()

    assert {row[0] for row in rows} == {"alembic_version"}


def test_batch_rebuild_keeps_message_constraints(tmp_path: Path) -> None:
    """Migration 0005 rebuilds `message`, which must not drop what was there.

    SQLite cannot ALTER in a foreign key, so batch mode copies the table; a
    lossy reflection would quietly take the account/folder cascades and the
    per-folder UID uniqueness with it.
    """
    db_path = tmp_path / "rebuild-test.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    command.upgrade(build_alembic_config(database_url), "head")

    with sqlite3.connect(db_path) as connection:
        foreign_keys = list(
            connection.execute("PRAGMA foreign_key_list(message)")
        )
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(message)")
        }
        unique_indexes = [
            row[1]
            for row in connection.execute("PRAGMA index_list(message)")
            if row[2]
        ]

    # (child column, parent table, on_delete) for every foreign key.
    links = {(row[3], row[2], row[6]) for row in foreign_keys}
    assert ("account_id", "account", "CASCADE") in links
    assert ("folder_id", "folder", "CASCADE") in links
    assert ("moved_to_folder_id", "folder", "SET NULL") in links
    assert "ix_message_account_id_message_id" in indexes
    assert unique_indexes, "the (account_id, folder_id, uid) constraint is gone"

    # The constraint has to actually bite, not merely exist in the schema.
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        account_id = "11111111-1111-1111-1111-111111111111"
        folder_id = "22222222-2222-2222-2222-222222222222"
        connection.execute(
            "INSERT INTO account (id, email, provider, imap_ssl, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (account_id, "a@example.com", "custom", 0, "active"),
        )
        connection.execute(
            "INSERT INTO folder (id, account_id, name, message_count) "
            "VALUES (?, ?, ?, ?)",
            (folder_id, account_id, "INBOX", 0),
        )
        connection.execute(
            "INSERT INTO message "
            "(id, account_id, folder_id, uid, to_json, cc_json, flags_json, "
            " remote_missing, is_read, is_starred) "
            "VALUES (?, ?, ?, ?, '[]', '[]', '[]', 0, 0, 0)",
            (
                "33333333-3333-3333-3333-333333333333",
                account_id,
                folder_id,
                7,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO message "
                "(id, account_id, folder_id, uid, to_json, cc_json, "
                " flags_json, remote_missing, is_read, is_starred) "
                "VALUES (?, ?, ?, ?, '[]', '[]', '[]', 0, 0, 0)",
                (
                    "44444444-4444-4444-4444-444444444444",
                    account_id,
                    folder_id,
                    7,
                ),
            )
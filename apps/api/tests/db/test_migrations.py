import sqlite3
from pathlib import Path

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

    assert {"remote_missing", "remote_missing_at"}.issubset(message_columns)
    assert "kind" in job_columns
    assert "last_reconcile_at" in cursor_columns


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
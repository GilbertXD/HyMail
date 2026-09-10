"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-10 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=True),
        sa.Column("imap_port", sa.Integer(), nullable=True),
        sa.Column("imap_ssl", sa.Boolean(), nullable=False),
        sa.Column("username", sa.String(length=320), nullable=True),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account"),
        sa.UniqueConstraint("email", name="uq_account_email"),
    )

    op.create_table(
        "folder",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("delimiter", sa.String(length=16), nullable=True),
        sa.Column("uidvalidity", sa.Integer(), nullable=True),
        sa.Column("uidnext", sa.Integer(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="fk_folder_account_id_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_folder"),
        sa.UniqueConstraint(
            "account_id",
            "name",
            name="uq_folder_account_id_name",
        ),
    )
    op.create_index(
        "ix_folder_account_id",
        "folder",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("folder_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=998), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("from_name", sa.String(length=255), nullable=True),
        sa.Column("from_addr", sa.String(length=320), nullable=True),
        sa.Column("to_json", sa.JSON(), nullable=False),
        sa.Column("cc_json", sa.JSON(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("internal_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("flags_json", sa.JSON(), nullable=False),
        sa.Column("raw_headers", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="fk_message_account_id_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folder.id"],
            name="fk_message_folder_id_folder",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message"),
        sa.UniqueConstraint(
            "account_id",
            "folder_id",
            "uid",
            name="uq_message_account_id_folder_id_uid",
        ),
    )
    op.create_index(
        "ix_message_account_id",
        "message",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_message_folder_id",
        "message",
        ["folder_id"],
        unique=False,
    )
    op.create_index(
        "ix_message_folder_id_date",
        "message",
        ["folder_id", "date"],
        unique=False,
    )
    op.create_index(
        "ix_message_folder_id_uid",
        "message",
        ["folder_id", "uid"],
        unique=False,
    )

    op.create_table(
        "sync_cursor",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("folder_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("uidvalidity", sa.Integer(), nullable=True),
        sa.Column("last_uid", sa.Integer(), nullable=False),
        sa.Column("uidnext", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="fk_sync_cursor_account_id_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folder.id"],
            name="fk_sync_cursor_folder_id_folder",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_cursor"),
        sa.UniqueConstraint(
            "account_id",
            "folder_id",
            name="uq_sync_cursor_account_id_folder_id",
        ),
    )
    op.create_index(
        "ix_sync_cursor_account_id",
        "sync_cursor",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_sync_cursor_folder_id",
        "sync_cursor",
        ["folder_id"],
        unique=False,
    )

    op.create_table(
        "sync_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("folder_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("uid_from", sa.Integer(), nullable=True),
        sa.Column("uid_to", sa.Integer(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="fk_sync_event_account_id_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folder.id"],
            name="fk_sync_event_folder_id_folder",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_event"),
    )
    op.create_index(
        "ix_sync_event_trace_id",
        "sync_event",
        ["trace_id"],
        unique=False,
    )
    op.create_index(
        "ix_sync_event_account_id",
        "sync_event",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_sync_event_folder_id",
        "sync_event",
        ["folder_id"],
        unique=False,
    )
    op.create_index(
        "ix_sync_event_account_id_id",
        "sync_event",
        ["account_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_sync_event_folder_id_id",
        "sync_event",
        ["folder_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sync_event_folder_id_id", table_name="sync_event")
    op.drop_index("ix_sync_event_account_id_id", table_name="sync_event")
    op.drop_index("ix_sync_event_folder_id", table_name="sync_event")
    op.drop_index("ix_sync_event_account_id", table_name="sync_event")
    op.drop_index("ix_sync_event_trace_id", table_name="sync_event")
    op.drop_table("sync_event")

    op.drop_index("ix_sync_cursor_folder_id", table_name="sync_cursor")
    op.drop_index("ix_sync_cursor_account_id", table_name="sync_cursor")
    op.drop_table("sync_cursor")

    op.drop_index("ix_message_folder_id_uid", table_name="message")
    op.drop_index("ix_message_folder_id_date", table_name="message")
    op.drop_index("ix_message_folder_id", table_name="message")
    op.drop_index("ix_message_account_id", table_name="message")
    op.drop_table("message")

    op.drop_index("ix_folder_account_id", table_name="folder")
    op.drop_table("folder")

    op.drop_table("account")
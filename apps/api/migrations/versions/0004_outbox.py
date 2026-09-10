"""outbox and flag columns

Revision ID: 0004_outbox
Revises: 0003_reconcile
Create Date: 2026-09-11 06:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_outbox"
down_revision: str | None = "0003_reconcile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "message",
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "message",
        sa.Column(
            "is_starred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "ix_message_folder_id_is_read",
        "message",
        ["folder_id", "is_read"],
        unique=False,
    )

    op.add_column(
        "sync_cursor",
        sa.Column(
            "last_flags_reconcile_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_table(
        "outbox_action",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("folder_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_outbox_action_account_id_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["message.id"],
            name="fk_outbox_action_message_id_message",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folder.id"],
            name="fk_outbox_action_folder_id_folder",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_action"),
    )
    op.create_index(
        "ix_outbox_action_account_id",
        "outbox_action",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_action_account_state",
        "outbox_action",
        ["account_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_action_message_type",
        "outbox_action",
        ["message_id", "type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_action_message_type", table_name="outbox_action")
    op.drop_index("ix_outbox_action_account_state", table_name="outbox_action")
    op.drop_index("ix_outbox_action_account_id", table_name="outbox_action")
    op.drop_table("outbox_action")

    op.drop_column("sync_cursor", "last_flags_reconcile_at")

    op.drop_index("ix_message_folder_id_is_read", table_name="message")
    op.drop_column("message", "is_starred")
    op.drop_column("message", "is_read")

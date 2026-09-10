"""reconcile support

Revision ID: 0003_reconcile
Revises: 0002_sync_job
Create Date: 2026-09-11 05:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_reconcile"
down_revision: str | None = "0002_sync_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "message",
        sa.Column(
            "remote_missing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "message",
        sa.Column(
            "remote_missing_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_message_folder_id_remote_missing",
        "message",
        ["folder_id", "remote_missing"],
        unique=False,
    )

    op.add_column(
        "sync_cursor",
        sa.Column(
            "last_reconcile_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "sync_job",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'sync'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sync_job", "kind")
    op.drop_column("sync_cursor", "last_reconcile_at")
    op.drop_index("ix_message_folder_id_remote_missing", table_name="message")
    op.drop_column("message", "remote_missing_at")
    op.drop_column("message", "remote_missing")

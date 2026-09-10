"""sync job queue

Revision ID: 0002_sync_job
Revises: 0001_initial_schema
Create Date: 2026-09-11 04:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sync_job"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_job",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("folder_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("batch_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_sync_job_account_id_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folder.id"],
            name="fk_sync_job_folder_id_folder",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_job"),
    )
    op.create_index(
        "ix_sync_job_account_id",
        "sync_job",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_sync_job_account_state_priority",
        "sync_job",
        ["account_id", "state", "priority"],
        unique=False,
    )
    op.create_index(
        "ix_sync_job_batch_id",
        "sync_job",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_sync_job_folder_id",
        "sync_job",
        ["folder_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sync_job_folder_id", table_name="sync_job")
    op.drop_index("ix_sync_job_batch_id", table_name="sync_job")
    op.drop_index("ix_sync_job_account_state_priority", table_name="sync_job")
    op.drop_index("ix_sync_job_account_id", table_name="sync_job")
    op.drop_table("sync_job")

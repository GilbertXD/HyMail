"""move attribution

Revision ID: 0005_moves
Revises: 0004_outbox
Create Date: 2026-09-11 07:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_moves"
down_revision: str | None = "0004_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite cannot ALTER in a foreign key, so the column and its constraint
    # go through batch mode, which rebuilds the table.
    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "moved_to_folder_id",
                sa.Uuid(as_uuid=True),
                nullable=True,
            )
        )
        # SET NULL rather than CASCADE: losing the destination folder must not
        # delete the message that used to live in it.
        batch_op.create_foreign_key(
            "fk_message_moved_to_folder_id_folder",
            "folder",
            ["moved_to_folder_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Matching a message that vanished from one folder against the same
    # Message-ID in another is the move-detection query.
    op.create_index(
        "ix_message_account_id_message_id",
        "message",
        ["account_id", "message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_message_account_id_message_id", table_name="message")
    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_message_moved_to_folder_id_folder",
            type_="foreignkey",
        )
        batch_op.drop_column("moved_to_folder_id")

"""
Revision ID: 0516_backfill_rte_default
Revises: 0515_add_created_by_id_to_files
Create Date: 2026-07-06

Backfill all existing users to have default_editor_is_rte = true and change the
column server default to true so new users also get RTE by default.
"""

from alembic import op
import sqlalchemy as sa

revision = "0516_backfill_rte_default"
down_revision = "0515_add_created_by_id_to_files"


def upgrade():
    op.execute("UPDATE users SET default_editor_is_rte = true")
    op.alter_column(
        "users",
        "default_editor_is_rte",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "users",
        "default_editor_is_rte",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )

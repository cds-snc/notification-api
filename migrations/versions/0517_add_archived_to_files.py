"""
Revision ID: 0517_add_archived_to_files
Revises: 0516_backfill_rte_default
Create Date: 2026-07-08

Add archived column to files table.
"""

from alembic import op
import sqlalchemy as sa

revision = "0517_add_archived_to_files"
down_revision = "0516_backfill_rte_default"


def upgrade():
    op.add_column("files", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("files", "archived")

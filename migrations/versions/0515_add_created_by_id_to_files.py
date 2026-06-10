"""
Revision ID: 0515_add_created_by_id_to_files
Revises: 0514_add_files_table
Create Date: 2026-06-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0515_add_created_by_id_to_files"
down_revision = "0514_add_files_table"


def upgrade():
    op.add_column("files", sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("files_created_by_id_fkey", "files", "users", ["created_by_id"], ["id"])
    op.create_index("ix_files_created_by_id", "files", ["created_by_id"])


def downgrade():
    op.drop_index("ix_files_created_by_id", table_name="files")
    op.drop_constraint("files_created_by_id_fkey", "files", type_="foreignkey")
    op.drop_column("files", "created_by_id")

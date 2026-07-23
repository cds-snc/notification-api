"""
Revision ID: 0521_add_archived_columns
Revises: 0520_update_bounce_rate_susp
Create Date: 2026-07-23

Add archived_at and archived_by_id columns to the services and services_history
tables to provide a proper audit trail of who archived a service and when.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0521_add_archived_columns"
down_revision = "0520_update_bounce_rate_susp"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("services", sa.Column("archived_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("services", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column("services_history", sa.Column("archived_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("services_history", sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("services", "archived_by_id")
    op.drop_column("services", "archived_at")
    op.drop_column("services_history", "archived_by_id")
    op.drop_column("services_history", "archived_at")

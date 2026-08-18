"""
Revision ID: 0525_add_callback_suspended_by_user
Revises: 0524_update_callback_susp_word
Create Date: 2026-08-18

Add manual suspension attribution for service callback APIs.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0525_add_callback_suspended_by_user"
down_revision = "0524_update_callback_susp_word"


def upgrade():
    op.add_column(
        "service_callback_api",
        sa.Column("suspended_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "service_callback_api_history",
        sa.Column("suspended_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade():
    op.drop_column("service_callback_api", "suspended_by_user_id")
    op.drop_column("service_callback_api_history", "suspended_by_user_id")

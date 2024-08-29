"""
Revision ID: 0460_new_service_columns
Revises: 0459_add_sensitive
Create Date: 2024-06-27 13:32:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0460_new_service_columns"
down_revision = "0459_add_sensitive"


def upgrade():
    op.add_column("service_callback_api", sa.Column("is_suspended", sa.Boolean(), nullable=True))
    op.add_column("service_callback_api_history", sa.Column("is_suspended", sa.Boolean(), nullable=True))
    op.add_column("service_callback_api", sa.Column("suspended_at", sa.DateTime(), nullable=True))
    op.add_column("service_callback_api_history", sa.Column("suspended_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("service_callback_api", "is_suspended")
    op.drop_column("service_callback_api_history", "is_suspended")
    op.drop_column("service_callback_api", "suspended_at")
    op.drop_column("service_callback_api_history", "suspended_at")

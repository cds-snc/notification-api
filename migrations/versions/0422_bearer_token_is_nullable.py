"""

Revision ID: 0422_bearer_token_is_nullable
Revises: 0421_add_sms_daily_limit
Create Date: 2022-09-07 16:00:00

"""
import sqlalchemy as sa
from alembic import op

revision = "0422_bearer_token_is_nullable"
down_revision = "0421_add_sms_daily_limit"


def upgrade():
    op.alter_column("service_callback_api", "bearer_token", nullable=True)


def downgrade():
    op.alter_column("service_callback_api", "bearer_token", nullable=False, server_default='')

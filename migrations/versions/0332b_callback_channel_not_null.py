"""

Revision ID: 0332b_callback_channel_not_null
Revises: 0332a_bearer_token_nullable
Create Date: 2021-08-06

"""
from alembic import op

from app.constants import WEBHOOK_CHANNEL_TYPE

revision = '0332b_callback_channel_not_null'
down_revision = '0332a_bearer_token_nullable'


def upgrade():
    op.execute(f"update service_callback set callback_channel = '{WEBHOOK_CHANNEL_TYPE}'"
               f"where callback_channel is null")  # nosec
    op.execute(f"update service_callback_history set callback_channel = '{WEBHOOK_CHANNEL_TYPE}'"
               f"where callback_channel is null")  # nosec
    op.alter_column('service_callback', 'callback_channel', nullable=False)
    op.alter_column('service_callback_history', 'callback_channel', nullable=False)


def downgrade():
    op.alter_column('service_callback', 'callback_channel', nullable=True)
    op.alter_column('service_callback_history', 'callback_channel', nullable=True)

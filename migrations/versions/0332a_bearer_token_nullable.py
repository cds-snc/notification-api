"""

Revision ID: 0332a_bearer_token_nullable
Revises: 0332_service_callback_channel
Create Date: 2021-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = '0332a_bearer_token_nullable'
down_revision = '0332_service_callback_channel'


def upgrade():
    op.alter_column('service_callback', 'bearer_token', nullable=True)
    op.alter_column('service_callback_history', 'bearer_token', nullable=True)

    op.create_check_constraint(
        "ck_bearer_token_required_for_webhook_channel",
        "service_callback",
        "NOT (callback_channel = 'webhook' and bearer_token is null)"
    )
    op.create_check_constraint(
        "ck_bearer_token_required_for_webhook_channel",
        "service_callback_history",
        "NOT (callback_channel = 'webhook' and bearer_token is null)"
    )


def downgrade():
    op.drop_constraint('ck_bearer_token_required_for_webhook_channel', 'service_callback')
    op.drop_constraint('ck_bearer_token_required_for_webhook_channel', 'service_callback_history')

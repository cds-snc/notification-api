"""

Revision ID: 0329_notification_status
Revises: 0328_identity_provider_user_id
Create Date: 2021-05-07

"""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from app.models import NOTIFICATION_STATUS_TYPES_COMPLETED

revision = '0329_notification_status'
down_revision = '0328_identity_provider_user_id'


def upgrade():
    default_statuses = f"'{json.dumps({'statuses': NOTIFICATION_STATUS_TYPES_COMPLETED})}'::jsonb"
    op.add_column('service_callback_api', sa.Column(
        'notification_statuses', JSONB(astext_type=sa.Text()), nullable=False,
        default=text(default_statuses), server_default=text(default_statuses)
    ))
    op.add_column('service_callback_api_history', sa.Column(
        'notification_statuses', JSONB(), nullable=True
    ))


def downgrade():
    op.drop_column('service_callback_api', 'notification_statuses')
    op.drop_column('service_callback_api_history', 'notification_statuses')

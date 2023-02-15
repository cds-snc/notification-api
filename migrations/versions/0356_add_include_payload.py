"""

Revision ID: 0356_add_include_payload
Revises: 0355_sms_billing
Create Date: 2023-02-13 16:37:56.265491

"""
from alembic import op
import sqlalchemy as sa

revision = '0356_add_include_payload'
down_revision = '0355_sms_billing'


def upgrade():
    op.add_column('service_callback', sa.Column('include_provider_payload', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('service_callback_history', sa.Column('include_provider_payload', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('service_callback', 'include_provider_payload')
    op.drop_column('service_callback_history', 'include_provider_payload')

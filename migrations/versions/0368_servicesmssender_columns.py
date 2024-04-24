"""
Revision ID: 0368_servicesmssender_columns
Revises: 0367_add_auth_parameter
Create Date: 2024-04-22 14:20:28.054509
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0368_servicesmssender_columns'
down_revision = '0367_add_auth_parameter'


def upgrade():
    op.add_column('service_sms_senders', sa.Column('description', sa.String(length=256), nullable=True))
    op.add_column('service_sms_senders', sa.Column('provider_id', postgresql.UUID(), nullable=True))
    op.create_foreign_key('service_sms_senders_provider_id_fkey', 'service_sms_senders', 'provider_details', ['provider_id'], ['id'])


def downgrade():
    op.drop_constraint('service_sms_senders_provider_id_fkey', 'service_sms_senders', type_='foreignkey')
    op.drop_column('service_sms_senders', 'provider_id')
    op.drop_column('service_sms_senders', 'description')

"""

Revision ID: 0315_update_service
Revises: 0314_add_pinpoint_provider
Create Date: 2021-01-12 11:02:56.906384

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = '0315_update_service'
down_revision = '0314_add_pinpoint_provider'


def upgrade():
    op.add_column('services', sa.Column('email_provider_id', postgresql.UUID, nullable=True))
    op.create_foreign_key(
        constraint_name='services_email_provider_id_fkey',
        source_table='services',
        referent_table='provider_details',
        local_cols=['email_provider_id'],
        remote_cols=['id']
    )
    op.add_column('services', sa.Column('sms_provider_id', postgresql.UUID, nullable=True))
    op.create_foreign_key(
        constraint_name='services_sms_provider_id_fkey',
        source_table='services',
        referent_table='provider_details',
        local_cols=['sms_provider_id'],
        remote_cols=['id']
    )
    op.add_column('services_history', sa.Column('email_provider_id', postgresql.UUID, nullable=True))
    op.add_column('services_history', sa.Column('sms_provider_id', postgresql.UUID, nullable=True))


def downgrade():
    op.drop_column('services', 'email_provider_id')
    op.drop_column('services', 'sms_provider_id')
    op.drop_column('services_history', 'email_provider_id')
    op.drop_column('services_history', 'sms_provider_id')

"""

Revision ID: 0375_add_key_revoked
Revises: 0374_add_expected_cadence
Create Date: 2025-02-06 21:50:38.351026

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0375_add_key_revoked'
down_revision = '0374_add_expected_cadence'


def upgrade():
    op.add_column('api_keys', sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_index('uix_service_to_key_name', table_name='api_keys', postgresql_where='(expiry_date IS NULL)')
    op.add_column('api_keys_history', sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('api_keys_history', 'revoked')
    op.create_index('uix_service_to_key_name', 'api_keys', ['service_id', 'name'], unique=True, postgresql_where='(expiry_date IS NULL)')
    op.drop_column('api_keys', 'revoked')

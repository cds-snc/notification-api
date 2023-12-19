"""

Revision ID: 0367_add_auth_parameter
Revises: 0366_add_sessions_table
Create Date: 2023-12-04 21:59:53.602687

"""
from alembic import op
import sqlalchemy as sa

revision = '0367_add_auth_parameter'
down_revision = '0366_add_sessions_table'


def upgrade():
    op.add_column('inbound_numbers', sa.Column('auth_parameter', sa.String(), nullable=True))
    op.create_index(op.f('ix_inbound_numbers_service_id'), 'inbound_numbers', ['service_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_inbound_numbers_service_id'), table_name='inbound_numbers')
    op.drop_column('inbound_numbers', 'auth_parameter')

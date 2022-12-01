"""
Revision ID: 0353_inbound_number_add_fields
Revises: 0352_updated_at_default
Create Date: 2022-11-07 19:30:54.448803
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0353_inbound_number_add_fields'
down_revision = '0352_updated_at_default'


def upgrade():
    op.add_column('inbound_numbers', sa.Column('url_endpoint', sa.String(), nullable=True))
    op.add_column('inbound_numbers', sa.Column('self_managed', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('inbound_numbers', 'self_managed')
    op.drop_column('inbound_numbers', 'url_endpoint')

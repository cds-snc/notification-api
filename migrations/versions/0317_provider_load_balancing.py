"""

Revision ID: 0317_provider_load_balancing
Revises: 0316_update_template_provider_id
Create Date: 2021-01-12 16:06:56.906384

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = '0317_provider_load_balancing'
down_revision = '0316_update_template_provider_id'


def upgrade():
    op.add_column('provider_details', sa.Column('load_balancing_weight', postgresql.INTEGER, nullable=True))
    op.add_column('provider_details_history', sa.Column('load_balancing_weight', postgresql.INTEGER, nullable=True))


def downgrade():
    op.drop_column('provider_details', 'load_balancing_weight')
    op.drop_column('provider_details_history', 'load_balancing_weight')

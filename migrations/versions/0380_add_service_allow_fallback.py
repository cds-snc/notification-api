"""

Revision ID: 0380_add_service_allow_fallback
Revises: 0379_remove_onsite
Create Date: 2025-01-24 12:23:09.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '0380_add_service_allow_fallback'
down_revision = '0379_remove_onsite'


def upgrade():
    op.add_column('services', sa.Column('allow_fallback', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('services_history', sa.Column('allow_fallback', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('services_history', 'allow_fallback')
    op.drop_column('services', 'allow_fallback')

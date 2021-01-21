"""

Revision ID: 0316_update_template_provider_id
Revises: 0315_update_service
Create Date: 2021-01-12 16:06:56.906384

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = '0316_update_template_provider_id'
down_revision = '0315_update_service'


def upgrade():
    op.add_column('templates', sa.Column('provider_id', postgresql.UUID, nullable=True))
    op.create_foreign_key(
        constraint_name='templates_provider_id_fkey',
        source_table='templates',
        referent_table='provider_details',
        local_cols=['provider_id'],
        remote_cols=['id']
    )
    op.add_column('templates_history', sa.Column('provider_id', postgresql.UUID, nullable=True))


def downgrade():
    op.drop_column('templates', 'provider_id')
    op.drop_column('templates_history', 'provider_id')

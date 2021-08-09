"""

Revision ID: 0333b_update_history_comm_item

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = '0333b_update_history_comm_item'
down_revision = '0333a_update_template_comm_item'


def upgrade():
    op.add_column('templates_history', sa.Column('communication_item_id', postgresql.UUID, nullable=True))


def downgrade():
    op.drop_column('templates_history', 'communication_item_id')

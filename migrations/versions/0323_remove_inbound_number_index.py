"""

Revision ID: 0323_remove_inbound_number_index
Revises: 0322_update_complaint_template
Create Date: 2021-03-31 17:00:00

"""

from alembic import op

revision = '0323_remove_inbound_number_index'
down_revision = '0322_update_complaint_template'


def upgrade():
    op.drop_index(op.f('ix_inbound_numbers_service_id'), table_name='inbound_numbers')


def downgrade():
    op.create_index(op.f('ix_inbound_numbers_service_id'), 'inbound_numbers', ['service_id'], unique=True)

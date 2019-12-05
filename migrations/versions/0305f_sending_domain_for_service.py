"""

Revision ID: 0305f_sending_domain_for_service
Revises: 0305e_account_change_type
Create Date: 2019-12-03 17:08:21.019759

"""
import sqlalchemy as sa
from alembic import op

revision = '0305f_sending_domain_for_service'
down_revision = '0305e_account_change_type'

def upgrade():
    op.add_column('services', sa.Column('sending_domain', sa.Text(), nullable=True))
    op.add_column('services_history', sa.Column('sending_domain', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('services', 'sending_domain')
    op.drop_column('services_history', 'sending_domain')

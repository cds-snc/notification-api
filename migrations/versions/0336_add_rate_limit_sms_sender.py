"""

Revision ID: 0336_add_rate_limit_sms_sender
Revises: 0335_add_billing_code
Create Date: 2021-09-07 15:28:07.577379

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0336_add_rate_limit_sms_sender'
down_revision = '0335_add_billing_code'


def upgrade():
    op.add_column('service_sms_senders', sa.Column('rate_limit', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('service_sms_senders', 'rate_limit')

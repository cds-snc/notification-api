"""

Revision ID: 0338_update_fact_notif_status
Revises: 0337a_rate_limit_interval
Create Date: 2021-11-17 16:05:59.231302

"""
from alembic import op
import sqlalchemy as sa


revision = '0338_update_fact_notif_status'
down_revision = '0337a_rate_limit_interval'


def upgrade():
    op.add_column('ft_notification_status', sa.Column('status_reason', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('ft_notification_status', 'status_reason')

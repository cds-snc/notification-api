"""
Revision ID: 0355_sms_billing
Revises: 0354_notification_sms_sender_id
Create Date: 2023-01-11 20:09:58.840087
"""

from alembic import op
import sqlalchemy as sa

revision = '0355_sms_billing'
down_revision = '0354_notification_sms_sender_id'


def upgrade():
    op.add_column('notifications', sa.Column('segments_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('notifications', sa.Column('cost_in_millicents', sa.Float(), nullable=False, server_default="0.0"))
    op.add_column('notification_history', sa.Column('segments_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('notification_history', sa.Column('cost_in_millicents', sa.Float(), nullable=False, server_default="0.0"))


def downgrade():
    op.drop_column('notification_history', 'cost_in_millicents')
    op.drop_column('notification_history', 'segments_count')
    op.drop_column('notifications', 'cost_in_millicents')
    op.drop_column('notifications', 'segments_count')

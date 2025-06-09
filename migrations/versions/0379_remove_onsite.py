"""
Revision ID: 0379_remove_onsite
Revises: 0378_sms_sender_length
Create Date: 2025-06-09 12:55:15.404047
"""

from alembic import op
import sqlalchemy as sa

revision = '0379_remove_onsite'
down_revision = '0378_sms_sender_length'


def upgrade():
    op.drop_column('templates', 'onsite_notification')
    op.drop_column('templates_history', 'onsite_notification')


def downgrade():
    op.add_column('templates_history', sa.Column('onsite_notification', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('templates', sa.Column('onsite_notification', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))

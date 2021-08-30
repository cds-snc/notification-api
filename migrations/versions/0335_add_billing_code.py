"""

Revision ID: 0335_add_billing_code
Revises: 0334_add_preferences_declined
Create Date: 2021-08-30 15:59:09.268214

"""
from alembic import op
import sqlalchemy as sa

revision = '0335_add_billing_code'
down_revision = '0334_add_preferences_declined'


def upgrade():
    op.add_column('notifications', sa.Column('billing_code', sa.String(length=256), nullable=True))
    op.add_column('notification_history', sa.Column('billing_code', sa.String(length=256), nullable=True))


def downgrade():
    op.drop_column('notifications', 'billing_code')
    op.drop_column('notification_history', 'billing_code')

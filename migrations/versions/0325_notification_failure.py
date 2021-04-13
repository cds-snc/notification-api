"""

Revision ID: 0325_notification_failure
Revises: 0324_complaint_feedback_id
Create Date: 2021-04-02 16:31:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0325_notification_failure'
down_revision = '0324_complaint_feedback_id'


def upgrade():
    op.add_column('notifications', sa.Column('failure_reason', sa.String(), nullable=True))
    op.add_column('notification_history', sa.Column('failure_reason', sa.String(), nullable=True))


def downgrade():
    op.drop_column('notifications', 'failure_reason')
    op.drop_column('notification_history', 'failure_reason')

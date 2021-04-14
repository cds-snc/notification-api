"""

Revision ID: 0326_notification_status_reason
Revises: 0325_notification_failure
Create Date: 2021-04-02 16:31:00

"""
from alembic import op

revision = '0326_notification_status_reason'
down_revision = '0325_notification_failure'


def upgrade():
    op.alter_column('notifications', 'failure_reason', nullable=True, new_column_name='status_reason')
    op.alter_column('notification_history', 'failure_reason', nullable=True, new_column_name='status_reason')


def downgrade():
    op.alter_column('notifications', 'status_reason', nullable=True, new_column_name='failure_reason')
    op.alter_column('notification_history', 'status_reason', nullable=True, new_column_name='failure_reason')

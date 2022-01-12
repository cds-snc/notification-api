"""

Revision ID: 0338b_pkey_constraint
Revises: 0338a_fact_notif_pkey_constraint
Create Date: 2022-01-12 14:54:59.108150

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0338b_pkey_constraint'
down_revision = '0338a_fact_notif_pkey_constraint'


def upgrade():
    op.drop_constraint('ft_notification_status_pkey', 'ft_notification_status', type_='primary')
    op.alter_column('ft_notification_status', 'status_reason', nullable=True)
    op.create_primary_key(
        "ft_notification_status_pkey",
        "ft_notification_status",
        [
            'bst_date', 'template_id', 'service_id', 'job_id',
            'notification_type', 'key_type', 'notification_status'
        ]
    )


def downgrade():
    op.drop_constraint('ft_notification_status_pkey', 'ft_notification_status', type_='primary')
    op.alter_column('ft_notification_status', 'status_reason', nullable=False, server_default='')
    op.create_primary_key(
        "ft_notification_status_pkey",
        "ft_notification_status",
        [
            'bst_date', 'template_id', 'service_id', 'job_id',
            'notification_type', 'key_type', 'notification_status', 'status_reason'
        ]
    )

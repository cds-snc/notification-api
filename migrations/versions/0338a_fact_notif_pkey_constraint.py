"""
Revision ID: 0338a_fact_notif_pkey_constraint
Revises: 0338_update_fact_notif_status
Create Date: 2022-01-12 10:36:46.420704
"""
from alembic import op

revision = '0338a_fact_notif_pkey_constraint'
down_revision = '0338_update_fact_notif_status'


def upgrade():
    op.drop_constraint('ft_notification_status_pkey', 'ft_notification_status', type_='primary')
    op.alter_column('ft_notification_status', 'status_reason', server_default='')
    op.create_primary_key(
        "ft_notification_status_pkey",
        "ft_notification_status",
        [
            'bst_date', 'template_id', 'service_id', 'job_id',
            'notification_type', 'key_type', 'notification_status', 'status_reason'
        ]
    )


def downgrade():
    op.drop_constraint('ft_notification_status_pkey', 'ft_notification_status', type_='primary')
    op.alter_column('ft_notification_status', 'status_reason', server_default=None)
    op.create_primary_key(
        "ft_notification_status_pkey",
        "ft_notification_status",
        [
            'bst_date', 'template_id', 'service_id', 'job_id',
            'notification_type', 'key_type', 'notification_status'
        ]
    )

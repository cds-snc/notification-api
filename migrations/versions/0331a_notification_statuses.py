"""

Revision ID: 0331a_notification_statuses
Revises: 0331_merge_service_apis
Create Date: 2021-07-08

"""
from alembic import op

revision = '0331a_notification_statuses'
down_revision = '0331_merge_service_apis'


def upgrade():
    op.alter_column('service_callback', 'notification_statuses', nullable=True)
    op.alter_column('service_callback_history', 'notification_statuses', nullable=True)
    op.create_check_constraint(
        "ck_statuses_not_null_if_delivery_status",
        "service_callback",
        "Not(callback_type = 'delivery_status' and notification_statuses is null)"
    )
    op.create_check_constraint(
        "ck_statuses_in_history_not_null_if_delivery_status",
        "service_callback_history",
        "Not(callback_type = 'delivery_status' and notification_statuses is null)"
    )


def downgrade():
    op.alter_column('service_callback', 'notification_statuses', nullable=False)
    op.alter_column('service_callback_history', 'notification_statuses', nullable=False)
    op.drop_constraint('ck_statuses_not_null_if_delivery_status', 'service_callback')
    op.drop_constraint('ck_statuses_in_history_not_null_if_delivery_status', 'service_callback_history')
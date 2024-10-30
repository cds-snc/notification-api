"""

Revision ID: 0331b_status_and_callback_types
Revises: 0331a_notification_statuses
Create Date: 2021-07-15

"""
import json

from alembic import op
from sqlalchemy import text

from app.constants import NOTIFICATION_STATUS_TYPES_COMPLETED

revision = '0331b_status_and_callback_types'
down_revision = '0331a_notification_statuses'


def upgrade():
    op.drop_constraint('ck_statuses_not_null_if_delivery_status', 'service_callback')

    op.execute(f"""
            UPDATE service_callback
            SET notification_statuses = NULL 
            WHERE callback_type != 'delivery_status'
        """)  # nosec

    op.create_check_constraint(
        "ck_notification_status_iff_delivery_status",
        "service_callback",
        "(callback_type = 'delivery_status' and notification_statuses is not null) or (callback_type != 'delivery_status' and notification_statuses is null)"
    )

    op.alter_column('service_callback', 'notification_statuses', server_default=None)

def downgrade():
    op.create_check_constraint(
        "ck_statuses_not_null_if_delivery_status",
        "service_callback",
        "Not(callback_type = 'delivery_status' and notification_statuses is null)"
    )

    curly_braces = "{}"

    op.drop_constraint('ck_notification_status_iff_delivery_status', 'service_callback')

    op.execute(f"""
            UPDATE service_callback
            SET notification_statuses = '{curly_braces}'
            WHERE callback_type != 'delivery_status'
        """)  # nosec

    default_statuses = f"'{json.dumps({'statuses': NOTIFICATION_STATUS_TYPES_COMPLETED})}'::jsonb"

    op.alter_column('service_callback', 'notification_statuses', server_default=text(default_statuses))


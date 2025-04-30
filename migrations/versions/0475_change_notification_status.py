"""

Revision ID: 0475_change_notification_status
Revises: 0474_add_feedback_reason_column
Create Date: 2025-02-11 15:37:00 EST

"""

from alembic import op

revision = "0475_change_notification_status"
down_revision = "0474_add_feedback_reason_column"

new_notification_status = "provider-failure"


def upgrade():
    op.execute("UPDATE notification_status_types set name = 'provider-failure' where name = 'pinpoint-failure'")


def downgrade():
    op.execute("UPDATE notification_status_types set name = 'pinpoint-failure' where name = 'provider-failure'")

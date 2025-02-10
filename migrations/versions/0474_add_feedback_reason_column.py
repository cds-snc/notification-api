"""

Revision ID: 0474_add_feedback_reason_column
Revises: 0473_change_pt_support_email
Create Date: 2025-02-05 14:40:00 EST

"""

import sqlalchemy as sa
from alembic import op

revision = "0474_add_feedback_reason_column"
down_revision = "0473_change_pt_support_email"

new_notification_status = "pinpoint-failure"


def upgrade():
    op.add_column("notifications", sa.Column("feedback_reason", sa.String(length=255), nullable=True))
    op.add_column("notification_history", sa.Column("feedback_reason", sa.String(length=255), nullable=True))

    op.create_index(
        op.f("ix_notifications_feedback_reason"),
        "notifications",
        ["feedback_reason"],
    )
    op.create_index(
        op.f("ix_notification_history_feedback_reason"),
        "notification_history",
        ["feedback_reason"],
    )

    op.execute("INSERT INTO notification_status_types (name) VALUES ('{}')".format(new_notification_status))


def downgrade():
    op.drop_index(op.f("ix_notifications_feedback_reason"), table_name="notifications")
    op.drop_index(op.f("ix_notification_history_feedback_reason"), table_name="notification_history")
    op.drop_column("notifications", "feedback_reason")
    op.drop_column("notification_history", "feedback_reason")
    op.execute("DELETE FROM notification_status_types WHERE name = '{}'".format(new_notification_status))

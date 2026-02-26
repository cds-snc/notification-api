"""Add billable generated column to notifications, notification_history, ft_notification_status

Revision ID: 0505_add_billable_column
Revises: 0504_fix_template_link
Create Date: 2026-02-26 00:00:00

"""
from alembic import op

revision = "0505_add_billable_column"
down_revision = "0504_fix_template_link"


def upgrade():
    op.execute(
        "ALTER TABLE notifications ADD COLUMN billable BOOLEAN GENERATED ALWAYS AS (sent_by IS NOT NULL) STORED"
    )
    op.execute(
        "ALTER TABLE notification_history ADD COLUMN billable BOOLEAN GENERATED ALWAYS AS (sent_by IS NOT NULL) STORED"
    )


def downgrade():
    op.drop_column("notification_history", "billable")
    op.drop_column("notifications", "billable")

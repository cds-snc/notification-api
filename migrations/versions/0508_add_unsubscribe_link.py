"""Add unsubscribe_link to notifications and has_unsubscribe_link to templates.

Revision ID: 0508_add_unsubscribe_link
Revises: 0507_sms_templates_parts
Create Date: 2026-03-24 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0508_add_unsubscribe_link"
down_revision = "0507_sms_templates_parts"


def upgrade():
    op.add_column("notifications", sa.Column("unsubscribe_link", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_unsubscribe_link_is_null_if_notification_not_an_email",
        "notifications",
        "notification_type = 'email' OR unsubscribe_link is null",
    )

    op.add_column("templates", sa.Column("has_unsubscribe_link", sa.Boolean(), nullable=True, server_default="false"))
    op.add_column(
        "templates_history", sa.Column("has_unsubscribe_link", sa.Boolean(), nullable=True, server_default="false")
    )
    op.create_check_constraint(
        "ck_templates_non_email_has_unsubscribe_false",
        "templates",
        "template_type = 'email' OR has_unsubscribe_link IS false",
    )
    op.create_check_constraint(
        "ck_templates_history_non_email_has_unsubscribe_false",
        "templates_history",
        "template_type = 'email' OR has_unsubscribe_link IS false",
    )


def downgrade():
    op.drop_constraint("ck_templates_history_non_email_has_unsubscribe_false", "templates_history")
    op.drop_constraint("ck_templates_non_email_has_unsubscribe_false", "templates")
    op.drop_column("templates_history", "has_unsubscribe_link")
    op.drop_column("templates", "has_unsubscribe_link")
    op.drop_constraint("ck_unsubscribe_link_is_null_if_notification_not_an_email", "notifications")
    op.drop_column("notifications", "unsubscribe_link")

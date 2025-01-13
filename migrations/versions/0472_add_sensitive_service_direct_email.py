"""

Revision ID: 0472_add_sensitive_service_direct_email
Revises: 0471_edit_limit_emails2
Create Date: 2025-01-13 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0472_add_sensitive_service_direct_email"
down_revision = "0471_edit_limit_emails2"

contact_us_template_id = current_app.config["CONTACT_FORM_SENSITIVE_SERVICE_EMAIL_TEMPLATE_ID"]
template_ids = [contact_us_template_id]


def upgrade():
    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    contact_us_content = "\n".join(
        [
            "Skipping Freshdesk: The user submitting the Contact Us form belongs to a sensitive Service. Contact us form data:",
            "((contact_us_content))",
            "",
            "___",
            "",
            "[FR] Skipping Freshdesk: The user submitting the Contact Us form belongs to a sensitive Service. Contact us form data:",
            "",
            "((contact_us_content))",
        ]
    )

    templates = [
        {
            "id": contact_us_template_id,
            "name": "Contact form direct email - sensitive service",
            "subject": "Notify Contact us form for sensitive service",
            "content": contact_us_content,
        },
    ]

    for template in templates:
        op.execute(
            template_insert.format(
                template["id"],
                template["name"],
                "email",
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                "priority",
            )
        )

        op.execute(
            template_history_insert.format(
                template["id"],
                template["name"],
                "email",
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                "priority",
            )
        )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

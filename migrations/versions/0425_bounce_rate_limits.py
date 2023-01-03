"""
Revision ID: 0425_bounce_rate_limits

Revises: 0424_sms_templates_in_redacted

Create Date: 2022-12-28 00:00:00
"""

from datetime import datetime
from alembic import op
from flask import current_app


revision = "0425_bounce_rate_limites"
down_revision = "0424_sms_templates_in_redacted"

bounce_rate_exceeded = current_app.config["BOUNCE_RATE_EXCEEDED_ID"]
bounce_rate_warning = current_app.config["BOUNCE_RATE_WARNING_ID"]

templates = [
    {
        "id": bounce_rate_exceeded,
        "name": "Bounce Rate Exceeded",
        "type": "email",
        "subject": "Notification service bounce rate exceeded",
        "content_lines": [
            'The bounce rate for your service, "((service_name))" has been exceeded. ',
            "",
            "To ensure we can provide reliable, uninterrupted service to all users of Notify, we temporarily suspended your service: ((service_name))",
            "",
            "To resume your service, please [contact us](((contact_us_url)))",
        ],
    },
    {
        "id": bounce_rate_warning,
        "name": "Bounce Rate Warning",
        "type": "email",
        "subject": "Notification service bounce rate warning",
        "content_lines": [
            "Hello ((name))" "" 'Your service, "((service_name))" is approaching the bounce rate limit.',
            "",
            "To ensure that your service is not suspended, please ensure that your recipient lists are up to date and contain valid email addresses",
            "",
            "To learn more about managing the bounce rate for your services [contact us](((contact_us_url)))",
        ],
    },
]


def upgrade():

    insert = """
    INSERT INTO {} (id, name, template_type, created_at, content, archived, service_id, subject,
    created_by_id, version, process_type, hidden)
    VALUES ('{}', '{}', '{}', current_timestamp, '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    for template in templates:
        for table_name in "templates", "templates_history":
            op.execute(
                insert.format(
                    table_name,
                    template["id"],
                    template["name"],
                    template["type"],
                    "\n".join(template["content_lines"]),
                    current_app.config["NOTIFY_SERVICE_ID"],
                    template.get("subject"),
                    current_app.config["NOTIFY_USER_ID"],
                    "normal",
                )
            )
        op.execute(
            f"""
            INSERT INTO template_redacted(
                template_id,
                redact_personalisation,
                updated_at,
                updated_by_id
            ) VALUES ('{template["id"]}', false, current_timestamp, '{current_app.config["NOTIFY_USER_ID"]}')
            """
        )


def downgrade():
    for template in templates:
        for table in "templates", "template_history":
            op.execute(f"DELETE FROM {table} where template_id = '{template['id']}'")
        op.execute(f"DELETE FROM template_redacted WHERE template_id = '{template['id']}'")

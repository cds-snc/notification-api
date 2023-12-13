"""
Revision ID: 0442_add_heartbeat_templates
Revises: 0441_add_apikey_revoke_email
Create Date: 2022-09-21 00:00:00
"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0442_add_heartbeat_templates"
down_revision = "0441_add_apikey_revoke_email"

templates = [
    {
        "id": current_app.config["HEARTBEAT_TEMPLATE_EMAIL_LOW"],
        "name": "HEARTBEAT_TEMPLATE_EMAIL_LOW",
        "template_type": "email",
        "content": "HEARTBEAT_TEMPLATE_EMAIL_LOW",
        "subject": "HEARTBEAT_TEMPLATE_EMAIL_LOW",
        "process_type": "bulk",
    },
    {
        "id": current_app.config["HEARTBEAT_TEMPLATE_EMAIL_MEDIUM"],
        "name": "HEARTBEAT_TEMPLATE_EMAIL_MEDIUM",
        "template_type": "email",
        "content": "HEARTBEAT_TEMPLATE_EMAIL_MEDIUM",
        "subject": "HEARTBEAT_TEMPLATE_EMAIL_MEDIUM",
        "process_type": "normal",
    },
    {
        "id": current_app.config["HEARTBEAT_TEMPLATE_EMAIL_HIGH"],
        "name": "HEARTBEAT_TEMPLATE_EMAIL_HIGH",
        "template_type": "email",
        "content": "HEARTBEAT_TEMPLATE_EMAIL_HIGH",
        "subject": "HEARTBEAT_TEMPLATE_EMAIL_HIGH",
        "process_type": "priority",
    },
    {
        "id": current_app.config["HEARTBEAT_TEMPLATE_SMS_LOW"],
        "name": "HEARTBEAT_TEMPLATE_SMS_LOW",
        "template_type": "sms",
        "content": "HEARTBEAT_TEMPLATE_SMS_LOW",
        "subject": "HEARTBEAT_TEMPLATE_SMS_LOW",
        "process_type": "bulk",
    },
    {
        "id": current_app.config["HEARTBEAT_TEMPLATE_SMS_MEDIUM"],
        "name": "HEARTBEAT_TEMPLATE_SMS_MEDIUM",
        "template_type": "sms",
        "content": "HEARTBEAT_TEMPLATE_SMS_MEDIUM",
        "subject": "HEARTBEAT_TEMPLATE_SMS_MEDIUM",
        "process_type": "normal",
    },
    {
        "id": current_app.config["HEARTBEAT_TEMPLATE_SMS_HIGH"],
        "name": "HEARTBEAT_TEMPLATE_SMS_HIGH",
        "template_type": "sms",
        "content": "HEARTBEAT_TEMPLATE_SMS_HIGH",
        "subject": "HEARTBEAT_TEMPLATE_SMS_HIGH",
        "process_type": "priority",
    },
]


def upgrade():
    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', False)
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', False)
    """

    for template in templates:
        op.execute(
            template_insert.format(
                template["id"],
                template["name"],
                template["template_type"],
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                template["process_type"],
            )
        )

        op.execute(
            template_history_insert.format(
                template["id"],
                template["name"],
                template["template_type"],
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                template["process_type"],
            )
        )


def downgrade():
    TEMPLATE_IDS = ",".join(["'{}'".format(x["id"]) for x in templates])

    op.execute("DELETE FROM notifications WHERE template_id in ({})".format(TEMPLATE_IDS))
    op.execute("DELETE FROM notification_history WHERE template_id in ({})".format(TEMPLATE_IDS))
    op.execute("DELETE FROM template_redacted WHERE template_id in ({})".format(TEMPLATE_IDS))
    op.execute("DELETE FROM templates_history WHERE id in ({})".format(TEMPLATE_IDS))
    op.execute("DELETE FROM templates WHERE id in ({})".format(TEMPLATE_IDS))

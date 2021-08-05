"""

Revision ID: 0321_daily_limit_updated
Revises: 0320_remove_smtp
Create Date: 2021-05-18 13:37:42

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0321_daily_limit_updated"
down_revision = "0320_remove_smtp"

daily_limit_updated_id = current_app.config["DAILY_LIMIT_UPDATED_TEMPLATE_ID"]

template_ids = [daily_limit_updated_id]


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

    content = "\n".join(
        [
            "Hello ((name)),",
            "",
            "The daily limit of ((service_name)) has just been updated. You can now send ((message_limit_en)) messages per day. This new limit is effective now.",
            "",
            "The GC Notify team",
            "",
            "___",
            "",
            "Bonjour ((name)),",
            "",
            "La limite quotidienne de ((service_name)) a été mise à jour. Vous pouvez désormais envoyer ((message_limit_fr)) messages par jour. Ce changement est effectif dès maintenant.",
            "",
            "L’équipe GC Notification",
        ]
    )

    templates = [
        {
            "id": daily_limit_updated_id,
            "name": "Daily limit updated",
            "subject": "Daily sending limit updated for ((service_name)) | Limite d’envoi quotidienne mise à jour pour ((service_name))",
            "content": content,
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
                "normal",
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
                "normal",
            )
        )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

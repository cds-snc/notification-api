"""

Revision ID: 0423_daily_email_limit_updated
Revises: 0422_add_billable_units
Create Date: 2022-09-21 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0432_daily_email_limit_templates"
down_revision = "0431_add_pt_organisation_type"

near_email_limit_template_id = current_app.config["NEAR_DAILY_EMAIL_LIMIT_TEMPLATE_ID"]
at_email_limit_template_id = current_app.config["REACHED_DAILY_EMAIL_LIMIT_TEMPLATE_ID"]
daily_email_limit_updated_id = current_app.config["DAILY_EMAIL_LIMIT_UPDATED_TEMPLATE_ID"]

template_ids = [near_email_limit_template_id, at_email_limit_template_id, daily_email_limit_updated_id]


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

    near_email_limit_content = "\n".join(
        [
            "Hello ((name)),",
            "",
            "((service_name)) just reached 80% of its daily email limit of ((message_limit_en)) messages. Your service will be blocked from sending email if you go above the daily limit by the end of the day.",
            "",
            "You can request a limit increase by [contacting us](((contact_url))).",
            "",
            "The GC Notify team",
            "",
            "___",
            "",
            "Bonjour ((name)),",
            "",
            "((service_name)) vient d’atteindre 80% de sa limite quotidienne de ((message_limit_fr)) courriels. Votre service ne pourra plus envoyer de courriels si vous allez au-delà de votre limite d’ici la fin de journée.",
            "",
            "Vous pouvez demander à augmenter cette limite en [nous contactant](((contact_url))).",
            "",
            "L’équipe GC Notification",
        ]
    )

    reached_email_limit_content = "\n".join(
        [
            "Hello ((name)),",
            "",
            "((service_name)) has reached its daily email limit of ((message_limit_en)) messages. Your service has been blocked from sending email messages until tomorrow.",
            "",
            "You can request a limit increase by [contacting us](((contact_url))).",
            "",
            "The GC Notify team",
            "",
            "___",
            "",
            "Bonjour ((name)),",
            "",
            "((service_name)) vient d’atteindre sa limite quotidienne de ((message_limit_fr)) courriels. Votre service ne peut plus envoyer de courriels jusqu’à demain.",
            "",
            "Vous pouvez demander à augmenter cette limite en [nous contactant](((contact_url))).",
            "",
            "L’équipe GC Notification",
        ]
    )

    daily_email_limit_updated_content = "\n".join(
        [
            "Hello ((name)),",
            "",
            "The daily email limit of ((service_name)) has just been updated. You can now send ((message_limit_en)) emails per day. This new limit is effective now.",
            "",
            "The GC Notify team",
            "",
            "___",
            "",
            "Bonjour ((name)),",
            "",
            "La limite quotidienne de courriels de ((service_name)) a été mise à jour. Vous pouvez désormais envoyer ((message_limit_fr)) courriels par jour. Ce changement est effectif dès maintenant.",
            "",
            "L’équipe GC Notification",
        ]
    )

    templates = [
        {
            "id": near_email_limit_template_id,
            "name": "Near daily EMAIL limit",
            "subject": "Action required: 80% of daily email sending limit reached for ((service_name)) | Action requise: 80% de la limite d’envoi quotidienne atteinte pour ((service_name))",
            "content": near_email_limit_content,
        },
        {
            "id": at_email_limit_template_id,
            "name": "Daily EMAIL limit reached",
            "subject": "Action required: Daily email sending limit reached for ((service_name)) | Action requise: Limite d’envoi quotidienne atteinte pour ((service_name)) )",
            "content": reached_email_limit_content,
        },
        {
            "id": daily_email_limit_updated_id,
            "name": "Daily EMAIL limit updated",
            "subject": "Daily email sending limit updated for ((service_name)) | Limite d’envoi quotidienne mise à jour pour ((service_name))",
            "content": daily_email_limit_updated_content,
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

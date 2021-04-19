"""

Revision ID: 0319_warn_daily_limits
Revises: 0318_template_process_type_bulk
Create Date: 2021-04-16 13:37:42

"""
from datetime import datetime

from alembic import op
from flask import current_app


revision = '0319_warn_daily_limits'
down_revision = '0318_template_process_type_bulk'

near_limit_template_id = current_app.config['NEAR_DAILY_LIMIT_TEMPLATE_ID']
at_limit_template_id = current_app.config['REACHED_DAILY_LIMIT_TEMPLATE_ID']

template_ids = [near_limit_template_id, at_limit_template_id]


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

    near_daily_limit_content = '\n'.join([
        "Hello ((name)),",
        "",
        "((service_name)) just reached 80% of its daily limit of ((message_limit_en)) messages. Your service will be blocked from sending if you go above the daily limit by the end of the day.",
        "",
        "You can request a limit increase by [contacting us](((contact_url))).",
        "",
        "The GC Notify team",
        "",
        "___",
        "",
        "Bonjour ((name)),",
        "",
        "((service_name)) vient d’atteindre 80% de sa limite quotidienne de ((message_limit_fr)) messages. Votre service ne pourra plus envoyer de messages si vous allez au-delà de votre limite d’ici la fin de journée.",
        "",
        "Vous pouvez demander à augmenter cette limite en [nous contactant](((contact_url))).",
        "",
        "L’équipe GC Notification",
    ])

    reached_limit_content = '\n'.join([
        "Hello ((name)),",
        "",
        "((service_name)) has reached its daily limit of ((message_limit_en)) messages. Your service has been blocked from sending messages until tomorrow.",
        "",
        "You can request a limit increase by [contacting us](((contact_url))).",
        "",
        "The GC Notify team",
        "",
        "___",
        "",
        "Bonjour ((name)),",
        "",
        "((service_name)) vient d’atteindre sa limite quotidienne de ((message_limit_fr)) messages. Votre service ne peut plus envoyer de messages jusqu’à demain.",
        "",
        "Vous pouvez demander à augmenter cette limite en [nous contactant](((contact_url))).",
        "",
        "L’équipe GC Notification",
    ])

    templates = [
        {
            "id": near_limit_template_id,
            "name": "Near daily limit",
            "subject": "Action required: 80% of daily sending limit reached for ((service_name)) | Action requise: 80% de la limite d’envoi quotidienne atteinte pour ((service_name))",
            "content": near_daily_limit_content,
        },
        {
            "id": at_limit_template_id,
            "name": "Daily limit reached",
            "subject": "Action required: Daily sending limit reached for ((service_name)) | Action requise: Limite d’envoi quotidienne atteinte pour ((service_name)) )",
            "content": reached_limit_content,
        },
    ]

    for template in templates:
        op.execute(
            template_history_insert.format(
                template['id'],
                template['name'],
                'email',
                datetime.utcnow(),
                template['content'],
                current_app.config['NOTIFY_SERVICE_ID'],
                template['subject'],
                current_app.config['NOTIFY_USER_ID'],
                'normal'
            )
        )

        op.execute(
            template_insert.format(
                template['id'],
                template['name'],
                'email',
                datetime.utcnow(),
                template['content'],
                current_app.config['NOTIFY_SERVICE_ID'],
                template['subject'],
                current_app.config['NOTIFY_USER_ID'],
                'normal'
            )
        )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

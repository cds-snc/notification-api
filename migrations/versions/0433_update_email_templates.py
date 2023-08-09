"""

Revision ID: 0433_update_email_templates
Revises: 0432_daily_email_limit_templates
Create Date: 2023-08-08 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0433_update_email_templates"
down_revision = "0432_daily_email_limit_templates"

near_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "((service_name)) can send ((message_limit_en)) emails per day. You’ll be blocked from sending if you exceed that limit before 7pm Eastern Time. Check [your current local time](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](https://notification.canada.ca/contact). We’ll respond within 1 business day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "La limite quotidienne d’envoi est de ((message_limit_fr)) courriels par jour pour ((service_name)). Si vous dépassez cette limite avant 19 heures, heure de l’Est, vos envois seront bloqués.",
        "",
        "Comparez [les heures officielles au Canada](https://nrc.canada.ca/fr/horloge-web/).",
        "",
        "Veuillez [nous contacter](https://notification.canada.ca/contact) si vous souhaitez augmenter votre limite d’envoi. Nous vous répondrons en un jour ouvrable.",
        "",
        "L’équipe Notification GC",
    ]
)


reached_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "((service_name)) has sent ((message_limit_en)) emails today.",
        "",
        "You can send more messages after 7pm Eastern Time. Compare [official times across Canada](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](https://notification.canada.ca/contact). We’ll respond within 1 business day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Aujourd’hui, ((message_limit_fr)) courriels ont été envoyés pour ((service_name)).",
        "",
        "Vous pourrez envoyer davantage de courriels après 19 heures, heure de l’Est. Comparez [les heures officielles au Canada](https://nrc.canada.ca/fr/horloge-web/).",
        "",
        "Veuillez [nous contacter](https://notification.canada.ca/contact) si vous désirez augmenter votre limite d’envoi. Nous vous répondrons en un jour ouvrable.",
        "",
        "L’équipe Notification GC",
    ]
)

updated_content =  "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "You can now send ((message_limit_en)) email messages per day.",
        "",
        "The GC Notify Team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Vous pouvez désormais envoyer ((message_limit_fr)) courriels par jour.",
        "",
        "L’équipe Notification GC",
    ]
)

templates = [
    {
        "id": current_app.config["NEAR_DAILY_EMAIL_LIMIT_TEMPLATE_ID"],
        "name": "Near daily EMAIL limit",
        "template_type": "email",
        "content": near_content,
        "subject": "((service_name)) is near its daily limit for emails. | La limite quotidienne d’envoi de courriels est presque atteinte pour ((service_name)).",
        "process_type": "priority",
    },
    {
        "id": current_app.config["REACHED_DAILY_EMAIL_LIMIT_TEMPLATE_ID"],
        "name": "Daily EMAIL limit reached",
        "template_type": "email",
        "content": reached_content,
        "subject": "((service_name)) has reached its daily limit for email messages | La limite quotidienne d’envoi de courriels atteinte pour ((service_name)).",
        "process_type": "priority",
    },
    {
        "id": current_app.config["DAILY_EMAIL_LIMIT_UPDATED_TEMPLATE_ID"],
        "name": "Daily EMAIL limit updated",
        "template_type": "email",
        "content": updated_content,
        "subject": "We’ve updated the daily email limit for ((service_name)) | Nous avons mis à jour la limite quotidienne de courriels pour ((service_name))",
        "process_type": "priority",
    },
]


def upgrade():
    conn = op.get_bind()

    for template in templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1

    template_update = """
        UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}'
        WHERE id = '{}'
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, '{}', false)
    """

    for template in templates:
        op.execute(
            template_update.format(
                template["content"],
                template["subject"],
                template["version"],
                datetime.utcnow(),
                template["id"],
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
                template["version"],
                template["process_type"],
            )
        )


def downgrade():
    pass

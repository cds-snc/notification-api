"""

Revision ID: 0434_update_email_templates_sms
Revises: 0433_update_email_templates
Create Date: 2023-08-09 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0434_update_email_templates_sms"
down_revision = "0433_update_email_templates"

near_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "((service_name)) can send ((message_limit_en)) text messages per day. You’ll be blocked from sending if you exceed that limit before ((limit_reset_time_et_12hr)) Eastern Time. Compare [official times across Canada](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](((contact_url))). We’ll respond within 1 business day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "((service_name)) peut envoyer ((message_limit_fr)) messages texte par jour. Si vous atteignez cette limite avant ((limit_reset_time_et_24hr)) heures, heure de l’Est, vos envois seront bloqués. Comparez [les heures officielles au Canada](https://nrc.canada.ca/fr/horloge-web/).",
        "",
        "Veuillez [nous contacter](((contact_url))) si vous désirez augmenter votre limite d’envoi. Nous vous répondrons en un jour ouvrable.",
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
        "((service_name)) has sent ((message_limit_en)) text messages today.",
        "",
        "You can send more messages after ((limit_reset_time_et_12hr)) Eastern Time. Compare [official times across Canada](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](((contact_url))). We’ll respond within 1 business day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Aujourd’hui, ((message_limit_fr)) messages texte ont été envoyés pour ((service_name)).",
        "",
        "Vous pourrez envoyer davantage de messages texte après ((limit_reset_time_et_24hr)) heures, heure de l’Est. Comparez [les heures officielles au Canada](https://nrc.canada.ca/fr/horloge-web/).",
        "",
        "Veuillez [nous contacter](((contact_url))) si vous désirez augmenter votre limite d’envoi. Nous vous répondrons en un jour ouvrable.",
        "",
        "L’équipe Notification GC",
    ]
)

updated_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "You can now send ((message_limit_en)) text messages per day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Vous pouvez désormais envoyer ((message_limit_fr)) messages texte par jour.",
        "",
        "L’équipe Notification GC",
    ]
)

templates = [
    {
        "id": current_app.config["NEAR_DAILY_SMS_LIMIT_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "((service_name)) is near its daily limit for text messages. | La limite quotidienne d’envoi de messages texte est presque atteinte pour ((service_name)).",
        "content": near_content,
        "process_type": "priority",
    },
    {
        "id": current_app.config["REACHED_DAILY_SMS_LIMIT_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "((service_name)) has reached its daily limit for text messages. | La limite quotidienne d’envoi de messages texte est atteinte pour ((service_name)).",
        "content": reached_content,
        "process_type": "priority",
    },
    {
        "id": current_app.config["DAILY_SMS_LIMIT_UPDATED_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "We’ve updated the daily limit for ((service_name)) | Limite quotidienne d’envoi mise à jour pour ((service_name)).",
        "content": updated_content,
        "process_type": "priority",
    },
]


def upgrade():
    conn = op.get_bind()

    for template in templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        name = conn.execute("select name from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1
        template["name"] = name[0]

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

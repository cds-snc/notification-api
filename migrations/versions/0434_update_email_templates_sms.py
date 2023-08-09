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
        "If a text message is long, it travels in fragments. The fragments assemble into 1 message for the recipient. Each fragment counts towards your daily limit.",
        "",
        "The number of fragments may be higher than the number of recipients. Complex factors determine how messages split into fragments. These factors include character count and type of characters used.",
        "",
        "((service_name)) can send ((message_limit_en)) text fragments per day. You’ll be blocked from sending if you exceed that limit before 7 pm Eastern Time. Check [your current local time](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](((contact_url))). We’ll respond within 1 business day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Lorsqu’un message texte est long, il se fragmente lors de la transmission. Tous les fragments sont rassemblés pour former un message unique pour le destinataire. Chaque fragment compte dans votre limite quotidienne.",
        "",
        "Le nombre de fragments peut être supérieur au nombre de destinataires. La division des messages en fragments dépend de facteurs complexes, dont le nombre de caractères et le type de caractères utilisés.",
        "",
        "La limite quotidienne d’envoi est de ((message_limit_fr)) fragments de message texte par jour pour ((service_name)). Si vous dépassez cette limite avant 19 heures, heure de l’Est, vos envois seront bloqués.",
        "",
        "Comparez [les heures officielles au Canada](https://nrc.canada.ca/fr/horloge-web/)." "",
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


templates = [
    {
        "id": current_app.config["NEAR_DAILY_SMS_LIMIT_TEMPLATE_ID"],
        "template_type": "email",
        "content": near_content,
        "process_type": "priority",
    },
    {
        "id": current_app.config["REACHED_DAILY_SMS_LIMIT_TEMPLATE_ID"],
        "template_type": "email",
        "content": reached_content,
        "process_type": "priority",
    },
]


def upgrade():
    conn = op.get_bind()

    for template in templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        subject = conn.execute("select subject from templates where id='{}'".format(template["id"])).fetchone()
        name = conn.execute("select name from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1
        template["subject"] = subject[0]
        template["name"] = name[0]

    template_update = """
        UPDATE templates SET content = '{}', version = '{}', updated_at = '{}'
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

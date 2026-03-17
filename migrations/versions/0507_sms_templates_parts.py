"""

Revision ID: 0507_sms_templates_parts
Revises: 0506_update_ft_billing
Create Date: 2026-03-16 00:00:00

Update SMS limit email templates to replace hardcoded "text messages" /
"messages texte" with ((message_type_en)) / ((message_type_fr)) variables
so the API can choose the correct wording at runtime based on
FF_USE_BILLABLE_UNITS.

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0507_sms_templates_parts"
down_revision = "0506_update_ft_billing"

near_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "((service_name)) has sent ((count_en)) out of its limit of ((message_limit_en)) ((message_type_en)) per 24 hours.",
        "",
        "**((service_name)) can send ((remaining_en)) more ((message_type_en)) until your limit resets at ((limit_reset_time_et_12hr)) Eastern Time.** Compare [official times across Canada](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](((contact_url))). We'll respond within 1 business day.",
        "",
        "The GC Notify team",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "((service_name)) a envoyé ((count_fr)) messages de sa limite de ((message_limit_fr)) ((message_type_fr)) par 24 heures.",
        "",
        "**((service_name)) peut encore envoyer ((remaining_fr)) messages d'ici à ce que votre limite de ((message_type_fr)) soit réinitialisée à ((limit_reset_time_et_24hr)), heure de l'Est.** Comparez les [heures officielles à travers le Canada](https://nrc.canada.ca/fr/horloge-web/).",
        "",
        "Pour demander une augmentation de votre limite, [veuillez nous joindre](((contact_url))). Nous vous répondrons en un jour ouvrable.",
        "",
        "L'équipe Notification GC",
    ]
)

reached_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "((service_name)) has sent ((message_limit_en)) ((message_type_en)) today.",
        "",
        "You can send more messages after ((limit_reset_time_et_12hr)) Eastern Time. Compare [official times across Canada](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](((contact_url))). We'll respond within 1 business day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Aujourd'hui, ((service_name)) a envoyé ((message_limit_fr)) ((message_type_fr)).",
        "",
        "Vous pourrez envoyer davantage de ((message_type_fr)) après ((limit_reset_time_et_24hr)) heures, heure de l'Est. Comparez [les heures officielles au Canada](https://nrc.canada.ca/fr/horloge-web/).",
        "",
        "Veuillez [nous contacter](((contact_url))) si vous désirez augmenter votre limite d'envoi. Nous vous répondrons en un jour ouvrable.",
        "",
        "L'équipe Notification GC",
    ]
)

updated_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "You can now send ((message_limit_en)) ((message_type_en)) per day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Vous pouvez désormais envoyer ((message_limit_fr)) ((message_type_fr)) par jour.",
        "",
        "L'équipe Notification GC",
    ]
)

templates = [
    {
        "id": current_app.config["NEAR_DAILY_SMS_LIMIT_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "((service_name)) is near its daily limit for text messages. | La limite quotidienne d'envoi de messages texte est presque atteinte pour ((service_name)).",
        "content": near_content,
        "process_type": "priority",
    },
    {
        "id": current_app.config["REACHED_DAILY_SMS_LIMIT_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "((service_name)) has reached its daily limit for text messages. | La limite quotidienne d'envoi de messages texte est atteinte pour ((service_name)).",
        "content": reached_content,
        "process_type": "priority",
    },
    {
        "id": current_app.config["DAILY_SMS_LIMIT_UPDATED_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "We've updated the daily limit for ((service_name)) | Limite quotidienne d'envoi mise à jour pour ((service_name)).",
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
        escaped_content = template["content"].replace("'", "''")
        escaped_subject = template["subject"].replace("'", "''")

        op.execute(
            template_update.format(
                escaped_content,
                escaped_subject,
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
                escaped_content,
                current_app.config["NOTIFY_SERVICE_ID"],
                escaped_subject,
                current_app.config["NOTIFY_USER_ID"],
                template["version"],
                template["process_type"],
            )
        )


def downgrade():
    pass

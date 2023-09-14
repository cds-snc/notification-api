"""

Revision ID: 0437_email_templates_msgs_left
Revises: 0436_add_columns_api_keys
Create Date: 2023-10-05 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0437_email_templates_msgs_left"
down_revision = "0436_add_columns_api_keys"

near_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "((service_name)) has sent ((count_en)) out of its limit of ((message_limit_en)) emails per 24 hours.",
        "",
        "**((service_name)) can send ((remaining_en)) more messages until your limit resets at ((limit_reset_time_et_12hr)) Eastern Time.** Compare official times across Canada](https://nrc.canada.ca/en/web-clock/).",
        "",
        "To request a limit increase, [contact us](((contact_url))). We’ll respond within 1 business day.",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "((service_name)) a envoyé ((count_fr)) courriels de sa limite de ((message_limit_fr)) courriels par 24 heures.",
        "",
        "**((service_name)) peut encore envoyer ((remaining_fr)) messages d’ici à ce que votre limite de courriels soit réinitialisée à ((limit_reset_time_et_24hr)), heure de l’Est.** Comparez les heures officielles à travers le Canada.",
        "",
        "Pour demander une augmentation de votre limite, [veuillez nous joindre](((contact_url))). Nous vous répondrons en un jour ouvrable.",
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

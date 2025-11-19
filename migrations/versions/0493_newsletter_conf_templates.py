"""

Revision ID: 0493_newsletter_conf_templates
Revises: 0492_add_service_del_template
Create Date: 2025-10-21 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0493_newsletter_conf_templates"
down_revision = "0492_add_service_del_template"

newsletter_confirmation_template_en_id = current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_EN"]
newsletter_confirmation_template_fr_id = current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_FR"]
template_ids = [newsletter_confirmation_template_en_id, newsletter_confirmation_template_fr_id]

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

    template_content_en = "\n".join(
        [
            "To confirm your subscription, select the following link:",
            "",
            "((confirmation_link))",
            "",
            "**You must use your Government of Canada email address to subscribe. We do not accept personal or non-federal government addresses.**",
            "",
            "We use a third-party application called Airtable to collect email addresses. For more information, read [Airtable’s privacy policy](https://www.airtable.com/company/privacy).",
            "",
            "To learn how GC Notify protects your privacy, read our [Privacy Statement](https://notification.canada.ca/privacy). ",
            "",
            "The GC Notify Team"
        ]
    )
    
    template_content_fr = "\n".join(
        [
            "Pour confirmer votre abonnement, suivez ce lien :",
            "",
            "((confirmation_link))",
            "",
            "**Vous devez vous inscrire en utilisant votre adresse courriel du gouvernement du Canada. Nous n’acceptons pas les adresses personnelles ou des autres paliers de gouvernement.**",
            "",
            "Nous employons un service tiers nommé Airtable pour collecter les adresses courriel. Pour plus de renseignements, consultez [l’avis de confidentialité de Airtable](https://www.airtable.com/company/privacy/fr)",
            "",
            "Pour en savoir plus sur la façon dont Notification GC assure la confidentialité de vos données, consultez notre [avis de confidentialité](https://notification.canada.ca/confidentialite).",
            "",
            "L’équipe Notification GC"
        ]
    )

    templates = [
        {
            "id": newsletter_confirmation_template_en_id,
            "name": "EN Newsletter subscription confirmation",
            "subject": "Welcome to the GC Notify newsletter",
            "content": template_content_en,
            "template_type": "email",  
            "process_type": "normal",
        },
        {
            "id": newsletter_confirmation_template_fr_id,
            "name": "FR Newsletter subscription confirmation",
            "subject": "Bienvenue à l’infolettre de Notification GC",
            "content": template_content_fr,
            "template_type": "email",  
            "process_type": "normal",
        },
    ]

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
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))


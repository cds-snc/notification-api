"""
Revision ID: 0518_add_bounce_susp_template
Revises: 0517_add_archived_to_files
Create Date: 2026-07-08

Add Notify template used when suspending a service for high email bounce rate.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0518_add_bounce_susp_template"
down_revision = "0517_add_archived_to_files"

bounce_rate_suspended_template_id = current_app.config["SERVICE_BOUNCE_RATE_SUSPENDED_TEMPLATE_ID"]
template_ids = [bounce_rate_suspended_template_id]


def _template_content():
    return "\n".join(
        [
            "[[fr]](la version française suit)[[/fr]]",
            "",
            "[[en]]",
            "# Your service has been suspended",
            "",
            "We’ve suspended **((service_name))** because its email bounce rate was **((bounce_rate))%** over the last 24 hours. This is above the 10% limit for **problem emails** permitted in our [Terms of Use](https://notification.canada.ca/terms).",
            "",
            "## Why this matters",
            "We care about providing a high-quality service for all public servants. When a service has a high bounce rate, we risk being blocked by email providers. If that happens, no one using GC Notify can send notifications to the public.",
            "",
            "## How to restore your service",
            "To resume sending, you’ll need to clean up your contact list:",
            "",
            "1. [Review your problem emails](((failed_notifications_url_en))) to identify invalid addresses.",
            "2. Remove or correct these addresses in your system before sending again.",
            "3. [Contact us](https://notification.canada.ca/en/contact) or reply to this email once your list is updated.",
            "",
            "Access your [service dashboard](((service_dashboard_url))) for more details.",
            "",
            "Our team is here to support you. If you need guidance on how to improve your delivery rates, please reach out.",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "# Votre service a été suspendu",
            "",
            "Nous avons suspendu **((service_name))** car son taux de rebond de courriels a été de **((bounce_rate)) %** au cours des dernières 24 heures. Cela dépasse la limite de 10 % d'**adresses problématiques** autorisée dans nos [conditions d'utilisation](https://notification.canada.ca/terms).",
            "",
            "## Pourquoi est-ce important?",
            "Nous tenons à fournir un service de haute qualité à tous les fonctionnaires. Lorsqu'un service a un taux de rebond élevé, nous risquons d'être bloqués par les fournisseurs de courriel. Si cela se produit, personne ne pourra envoyer de notifications au public via Notification GC.",
            "",
            "## Comment rétablir votre service",
            "Pour reprendre l'envoi, vous devrez nettoyer votre liste de contacts :",
            "",
            "1. [Vérifiez vos adresses problématiques](((failed_notifications_url_fr))) pour repérer les adresses invalides.",
            "2. Retirez ou corrigez ces adresses dans votre système avant de tenter un nouvel envoi.",
            "3. [Contactez-nous](https://notification.canada.ca/fr/contact) ou répondez à ce courriel une fois que votre liste aura été mise à jour.",
            "",
            "Consultez le [tableau de bord de votre service](((service_dashboard_url_fr))) pour plus de détails.",
            "",
            "Notre équipe est là pour vous soutenir. Si vous avez besoin de conseils sur la façon d'améliorer vos taux de livraison, n'hésitez pas à nous contacter.",
            "",
            "L’équipe Notification GC",
            "[[/fr]]",
        ]
    )


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

    template = {
        "id": bounce_rate_suspended_template_id,
        "name": "Service suspended - high bounce rate | Service suspendu - taux de rebond eleve",
        "subject": "Action required: ((service_name)) suspended for high bounce rate | Mesure requise : ((service_name)) suspendu pour taux de rebond eleve",
        "content": _template_content(),
        "template_type": "email",
        "process_type": "normal",
    }
    escaped_content = template["content"].replace("'", "''")

    op.execute(
        template_insert.format(
            template["id"],
            template["name"],
            template["template_type"],
            datetime.utcnow(),
            escaped_content,
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
            escaped_content,
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

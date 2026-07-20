"""
Revision ID: 0519_add_bounce_rate_warn_tmpl
Revises: 0518_add_bounce_susp_template
Create Date: 2026-07-15

Add Notify template used to warn a service about high email bounce rate
(potential suspension) when the volume threshold has not yet been reached.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0519_add_bounce_rate_warn_tmpl"
down_revision = "0518_add_bounce_susp_template"

bounce_rate_warning_template_id = current_app.config["SERVICE_SUSPENDED_WARNING_TEMPLATE_ID"]
template_ids = [bounce_rate_warning_template_id]


def _template_content():
    return "\n".join(
        [
            "[[fr]]"
            "",
            "(la version française suit)"
            "",
            "[[/fr]]",
            "",
            "[[en]]",
            "# Warning: ((service_name)) may be suspended from sending emails",
            "",
            "We've detected that **((service_name))** has an email bounce rate of **((bounce_rate))%** over the last 24 hours. This is above the 10% limit for **problem emails** permitted in our [Terms of Use](https://notification.canada.ca/terms).",
            "",
            "## Why this matters",
            "A high bounce rate means many of your emails are not reaching recipients. If your bounce rate remains above 10% once your service has sent enough emails, we will suspend **email sending** for your service to protect delivery for all GC Notify users.",
            "",
            "## What you should do now",
            "Take action before email sending is suspended:",
            "",
            "1. [Review your problem emails](((failed_notifications_url_en))) to identify invalid addresses.",
            "2. Remove or correct these addresses in your system before sending again.",
            "3. [Contact us](https://notification.canada.ca/en/contact) or reply to this email if you need help.",
            "",
            "Access your [service dashboard](((service_dashboard_url_en))) for more details.",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "# Avertissement : l’envoi de courriels pour ((service_name)) pourrait être suspendu",
            "",
            "Nous avons détecté que **((service_name))** a un taux de rebond de courriels de **((bounce_rate)) %** au cours des dernières 24 heures. Cela dépasse la limite de 10 % d'**adresses problématiques** autorisée dans nos [conditions d'utilisation](https://notification.canada.ca/terms).",
            "",
            "## Pourquoi est-ce important?",
            "Un taux de rebond élevé signifie que bon nombre de vos courriels n'atteignent pas les destinataires. Si votre taux de rebond demeure supérieur à 10 % une fois que votre service aura envoyé suffisamment de courriels, nous suspendrons l'envoi de courriels pour votre service afin de protéger la livraison pour tous les utilisateurs de Notification GC.",
            "",
            "## Ce que vous devriez faire maintenant",
            "Prenez des mesures avant que l'envoi de courriels ne soit suspendu :",
            "",
            "1. [Vérifiez vos adresses problématiques](((failed_notifications_url_fr))) pour repérer les adresses invalides.",
            "2. Retirez ou corrigez ces adresses dans votre système avant de tenter un nouvel envoi.",
            "3. [Contactez-nous](https://notification.canada.ca/fr/contact) ou répondez à ce courriel si vous avez besoin d'aide.",
            "",
            "Consultez le [tableau de bord de votre service](((service_dashboard_url_fr))) pour plus de détails.",
            "",
            "L'équipe Notification GC",
            "[[/fr]]",
        ]
    )


def upgrade():
    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, template_category_id, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, template_category_id, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    template = {
        "id": bounce_rate_warning_template_id,
        "name": "Service bounce rate warning | Avertissement de taux de rebond du service",
        "subject": "Warning: ((service_name)) email sending may be suspended | Avertissement : envoi de courriels pour ((service_name)) pourrait etre suspendu",
        "content": _template_content(),
        "template_type": "email",
        "template_category_id": "1d8ce435-a7e5-431b-aaa2-a418bc4d14f9"
    }
    escaped_content = template["content"].replace("'", "''")
    escaped_subject = template["subject"].replace("'", "''")

    op.execute(
        template_insert.format(
            template["id"],
            template["name"],
            template["template_type"],
            datetime.utcnow(),
            escaped_content,
            current_app.config["NOTIFY_SERVICE_ID"],
            escaped_subject,
            current_app.config["NOTIFY_USER_ID"],
            template["template_category_id"],
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
            template["template_category_id"],
        )
    )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

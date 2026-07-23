"""
Revision ID: 0520_update_bounce_rate_warn
Revises:  0520_update_bounce_rate_susp
Create Date: 2026-07-20

Update bounce-rate suspension template wording to clarify that email sending
is suspended, not the entire service.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0520_update_bounce_rate_warn"
down_revision = "0520_update_bounce_rate_susp"


def _update_template_content():
    return "\n".join(
        [
            "[[fr]]",
            "",
            "(la version française suit)",
            "",
            "[[/fr]]",
            "",
            "[[en]]",
            "# Warning: ((service_name)) may be suspended from sending emails",
            "",
            "We've detected that **((service_name))** has an email bounce rate of **((bounce_rate))%** over the last 24 hours. If your bounce rate reaches **10% or more** once your service has sent enough emails, we may suspend **email sending** for your service under our [Terms of Use](https://notification.canada.ca/terms?lang=en).",
            "",
            "## Why this matters",
            "A high bounce rate means many of your emails are not reaching recipients. Reducing invalid addresses helps protect delivery for your service and for all GC Notify users.",
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
            "Nous avons détecté que **((service_name))** a un taux de rebond de courriels de **((bounce_rate)) %** au cours des dernières 24 heures. Si votre taux de rebond atteint **10 % ou plus** une fois que votre service a envoyé suffisamment de courriels, nous pourrions suspendre l'envoi de courriels pour votre service, conformément à nos [conditions d'utilisation](https://notification.canada.ca/terms?lang=fr).",
            "",
            "## Pourquoi est-ce important?",
            "Un taux de rebond élevé signifie que bon nombre de vos courriels n'atteignent pas les destinataires. Corriger les adresses invalides aide à protéger la livraison pour votre service et pour l'ensemble des utilisateurs de Notification GC.",
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
    conn = op.get_bind()

    template_id = current_app.config["SERVICE_SUSPENDED_WARNING_TEMPLATE_ID"]

    current_version = conn.execute("select version from templates where id='{}'".format(template_id)).fetchone()
    name = conn.execute("select name from templates where id='{}'".format(template_id)).fetchone()
    current_category = conn.execute(
        "select template_category_id from templates where id='{}'".format(template_id)
    ).fetchone()

    new_version = (current_version[0] if current_version and current_version[0] is not None else 0) + 1
    template_name = name[0] if name else "Service suspended - high bounce rate | Service suspendu - taux de rebond eleve"
    template_category = current_category[0] if current_category is not None else None

    template_subject = "Warning: ((service_name)) email sending may be suspended | Avertissement : envoi de courriels pour ((service_name)) pourrait etre suspendu"
    template_content = _update_template_content()

    escaped_content = template_content.replace("'", "''")
    escaped_subject = template_subject.replace("'", "''")
    escaped_name = template_name.replace("'", "''")

    if template_category is not None:
        op.execute(
            "UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}', template_category_id = '{}' WHERE id = '{}'".format(
                escaped_content,
                escaped_subject,
                new_version,
                datetime.utcnow(),
                template_category,
                template_id,
            )
        )
    else:
        op.execute(
            "UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}' WHERE id = '{}'".format(
                escaped_content,
                escaped_subject,
                new_version,
                datetime.utcnow(),
                template_id,
            )
        )

    if template_category is not None and template_category != "":
        template_category_sql = "'{}'".format(template_category)
    else:
        template_category_sql = "NULL"

    op.execute(
        "INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject, created_by_id, version, hidden, template_category_id) VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, false, {})".format(
            template_id,
            escaped_name,
            "email",
            datetime.utcnow(),
            escaped_content,
            current_app.config["NOTIFY_SERVICE_ID"],
            escaped_subject,
            current_app.config["NOTIFY_USER_ID"],
            new_version,
            template_category_sql,
        )
    )


def downgrade():
    pass

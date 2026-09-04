"""
Revision ID: 0520_update_bounce_rate_susp
Revises: 0519_add_bounce_rate_warn_tmpl
Create Date: 2026-07-20

Update bounce-rate suspension template wording to clarify that email sending
is suspended, not the entire service.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0520_update_bounce_rate_susp"
down_revision = "0519_add_bounce_rate_warn_tmpl"


def _updated_template_content():
    return "\n".join(
        [
            "[[fr]]",
            "",
            "(la version française suit)",
            "",
            "[[/fr]]",
            "",
            "[[en]]",
            "# Email sending for ((service_name)) has been suspended",
            "",
            "We’ve suspended email sending for **((service_name))** because its email bounce rate was **((bounce_rate))%** over the last 24 hours. This is above the 10% limit for **problem emails** permitted in our [Terms of Use](https://notification.canada.ca/terms).",
            "",
            "## Why this matters",
            "We care about providing a high-quality service for all public servants. When a service has a high bounce rate, we risk being blocked by email providers. If that happens, no one using GC Notify can send notifications to the public.",
            "",
            "## How to restore email sending",
            "To resume sending, you’ll need to clean up your contact list:",
            "",
            "1. [Review your problem emails](((failed_notifications_url_en))) to identify invalid addresses.",
            "2. Remove or correct these addresses in your system before sending again.",
            "3. [Contact us](https://notification.canada.ca/en/contact) or reply to this email once your list is updated.",
            "",
            "Access your [service dashboard](((service_dashboard_url_en))) for more details.",
            "",
            "Our team is here to support you. If you need guidance on how to improve your delivery rates, please reach out.",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "# L'envoi de courriels pour ((service_name)) a été suspendu",
            "",
            "Nous avons suspendu l'envoi de courriels pour **((service_name))** car son taux de rebond de courriels a été de **((bounce_rate)) %** au cours des dernières 24 heures. Cela dépasse la limite de 10 % d'**adresses problématiques** autorisée dans nos [conditions d'utilisation](https://notification.canada.ca/terms).",
            "",
            "## Pourquoi est-ce important?",
            "Nous tenons à fournir un service de haute qualité à tous les fonctionnaires. Lorsqu'un service a un taux de rebond élevé, nous risquons d'être bloqués par les fournisseurs de courriel. Si cela se produit, personne ne pourra envoyer de notifications au public via Notification GC.",
            "",
            "## Comment rétablir l'envoi de courriels",
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
    conn = op.get_bind()

    template_id = current_app.config["SERVICE_BOUNCE_RATE_SUSPENDED_TEMPLATE_ID"]

    current_version = conn.execute("select version from templates where id='{}'".format(template_id)).fetchone()
    name = conn.execute("select name from templates where id='{}'".format(template_id)).fetchone()
    current_category = conn.execute(
        "select template_category_id from templates where id='{}'".format(template_id)
    ).fetchone()

    new_version = (current_version[0] if current_version and current_version[0] is not None else 0) + 1
    template_name = name[0] if name else "Service suspended - high bounce rate | Service suspendu - taux de rebond eleve"
    template_category = current_category[0] if current_category is not None else None

    template_subject = "Action required: ((service_name)) email sending suspended | Mesure requise : envoi de courriels pour ((service_name)) suspendu"
    template_content = _updated_template_content()

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

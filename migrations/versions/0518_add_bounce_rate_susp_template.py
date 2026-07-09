"""
Revision ID: 0518_add_bounce_rate_susp_template
Revises: 0517_add_archived_to_files
Create Date: 2026-07-08

Add Notify template used when suspending a service for high email bounce rate.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0518_add_bounce_rate_susp_template"
down_revision = "0517_add_archived_to_files"

bounce_rate_suspended_template_id = current_app.config["SERVICE_BOUNCE_RATE_SUSPENDED_TEMPLATE_ID"]
template_ids = [bounce_rate_suspended_template_id]


def _template_content():
    return "\n".join(
        [
            "[[fr]](la version française suit)[[/fr]]",
            "",
            "[[en]]",
            "We suspended ((service_name)) because its email bounce rate is ((bounce_rate))%, above the 10% limit in our [Terms of Use](https://notification.canada.ca/terms).",
            "",
            "To restore sending:",
            "- Review failed emails: ((failed_notifications_url))",
            "- Remove or correct invalid addresses",
            "- Reply to this email or [contact us](https://notification.canada.ca/en/contact) once this is done",
            "",
            "Service dashboard: ((service_dashboard_url))",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Nous avons suspendu ((service_name)) parce que son taux de rebond courriel est de ((bounce_rate)) %, au-dessus de la limite de 10 % de nos [conditions d'utilisation](https://notification.canada.ca/terms).",
            "",
            "Pour rétablir l’envoi :",
            "- Vérifiez les courriels en échec : ((failed_notifications_url))",
            "- Retirez ou corrigez les adresses invalides",
            "- Répondez à ce courriel ou [contactez-nous](https://notification.canada.ca/fr/contact) quand ce sera fait",
            "",
            "Tableau de bord du service : ((service_dashboard_url))",
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

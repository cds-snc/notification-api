"""

Revision ID: 0490_add_service_susp_template
Revises: 0489_add_suspended_columns
Create Date: 2025-10-20 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0490_add_service_susp_template"
down_revision = "0489_add_suspended_columns"

service_suspended_template_id = current_app.config["SERVICE_SUSPENDED_TEMPLATE_ID"]
template_ids = [service_suspended_template_id]

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

    service_suspended_content = "\n".join(
        [
            "[[fr]](la version française suit)[[/fr]]",
            "",
            "[[en]]",
            "You’ve deactivated your GC Notify account. ",
            "",
            "You cannot:",
            "- Access GC Notify services.",
            "- Manage teams or make changes on GC Notify.",
            "",
            "If you did not want to deactivate your account, immediately contact us.",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Vous avez désactivé votre compte GC Notify. Vous ne pouvez pas :",
            "",
            "- Accéder aux services GC Notify ;",
            "- Gérer les équipes ni effectuer des modifications sur GC Notify.",
            "",
            "Si vous ne souhaitez pas désactiver votre compte, contactez-nous immédiatement.",
            "",
            "L’équipe Notification GC",
            "[[/fr]]",
        ]
    )

    templates = [
        {
            "id": service_suspended_template_id,
            "name": "Service Suspend",
            "subject": "Account closed | Compte fermé",
            "content": "You’ve deactivated your GC Notify account.",
            "template_type": "email",  # Ensure this matches the ENUM definition in the database
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
                "normal",  # Changed to a shorter value to avoid potential issues
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
                "normal",  # Changed to a shorter value to avoid potential issues
            )
        )

def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

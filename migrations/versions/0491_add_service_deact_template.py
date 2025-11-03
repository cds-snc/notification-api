"""

Revision ID: 0492_add_service_del_template
Revises: 0491_split_deactivate_templates
Create Date: 2025-10-21 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0492_add_service_del_template"
down_revision = "0491_split_deactivate_templates"

service_deactivated_template_id = current_app.config["SERVICE_DEACTIVATED_TEMPLATE_ID"]
template_ids = [service_deactivated_template_id]

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
            "You or one of your team members has deleted ((service_name)). ",
            "",
            "You cannot:",
            "- Access, manage or make changes to ((service_name)).",
            "- Send messages from ((service_name)).",
            "",
            "If no one on your team deleted this service, immediately [contact us](https://notification.canada.ca/en/contact).",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Vous ou un membre de votre équipe avez supprimé le service ((service_name)).",
            "",
            "Vous ne pouvez plus :",
            "- Accéder, gérer ou apporter des changements au service ((service_name)).",
            "- Envoyer des messages provenant du service ((service_name)).",
            "",
            "Si vous ni votre équipe n’avez demandé de supprimer ce service, contactez-nous immédiatement.",
            "",
            "L’équipe Notification GC",
            "[[/fr]]",
        ]
    )

    templates = [
        {
            "id": service_deactivated_template_id,
            "name": "Service deleted",
            "subject": "((service_name)) deleted | ((service_name)) Compte fermé",
            "content": service_suspended_content,
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


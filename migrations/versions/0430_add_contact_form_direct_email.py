"""

Revision ID: 0430_add_contact_form_email
Revises: 0429_add_organisation_notes
Create Date: 2023-03-28 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0430_add_contact_form_email"
down_revision = "0429_add_organisation_notes"

contact_us_template_id = current_app.config["CONTACT_FORM_DIRECT_EMAIL_TEMPLATE_ID"]
template_ids = [contact_us_template_id]


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

    contact_us_content = "\n".join(
        [
            "Freshdesk integration has failed. Sending the following contact us form:",
            "((contact_us_content))",
            "",
            "___",
            "",
            "L’intégration de Freshdesk a échoué. Envoi du formulaire de contact suivant :",
            "",
            "((contact_us_content))",
        ]
    )

    templates = [
        {
            "id": contact_us_template_id,
            "name": "Contact form direct email",
            "subject": "Notify Contact us form",
            "content": contact_us_content,
        },
    ]

    for template in templates:
        op.execute(
            template_insert.format(
                template["id"],
                template["name"],
                "email",
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                "priority",
            )
        )

        op.execute(
            template_history_insert.format(
                template["id"],
                template["name"],
                "email",
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                "priority",
            )
        )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

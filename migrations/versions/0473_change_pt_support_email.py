"""

Revision ID: 0473_change_pt_support_email
Revises: 0472_add_direct_email_2
Create Date: 2025-01-29 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0473_change_pt_support_email"
down_revision = "0472_add_direct_email_2"

new_content = "\n".join(
    [
        "Skipping Freshdesk: The user submitting the Contact Us form belongs to a Province/Territory Service.",
        "",
        "Contact us form data:",
        "",
        "((contact_us_content))",
        "",
        "___",
        "",
        "Contournement de Freshdesk : l’utilisateur ou utilisatrice ayant soumis le formulaire « Nous joindre » fait partie d’un service provincial/territorial.",
        "",
        "Données du formulaire « Nous joindre » :",
        "",
        "((contact_us_content))",
    ]
)

templates = [
    {
        "id": current_app.config["CONTACT_FORM_SENSITIVE_SERVICE_EMAIL_TEMPLATE_ID"],
        "name": "Contact form direct email - PT service",
        "template_type": "email",
        "content": new_content,
        "subject": "Notify Contact us form for Province/Territory service / Formulaire « Nous joindre » de Notification GC pour un service provincial/territorial",
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

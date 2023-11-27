"""
Revision ID: 0441_add_apikey_revoke_email
Revises: 0440_add_index_n_history_comp
Create Date: 2022-09-21 00:00:00
"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0441_add_apikey_revoke_email"
down_revision = "0440_add_index_n_history_comp"

apikey_revoke_template_id = current_app.config["APIKEY_REVOKE_TEMPLATE_ID"]


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

    apikey_revoke_limit_content = "\n".join(
        [
            "[[fr]]",
            "(La version française suit)",
            "[[/fr]]",
            "",
            "[[en]]",
            "Hello,",
            "",
            "We discovered that an API key for service **''((service_name))''** is publicly available. GC Notify detected the key at ((public_location)). To protect GC Notify’s security, we revoked **''((key_name))''**.",
            "",
            "If you have questions or concerns, contact us.",
            "",
            "The GC Notify team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Bonjour,",
            "",
            "Nous avons découvert qu’une clé API du service **''((service_name))''** était à la disposition du public. Notification GC a détecté la clé à l’adresse suivante : ((public_location)). Pour la sécurité de Notification GC, nous avons révoqué **''((key_name))''**.",
            "",
            "Pour toutes questions, contactez-nous.",
            "",
            "L’équipe Notification GC",
            "[[/fr]]",
        ]
    )

    templates = [
        {
            "id": apikey_revoke_template_id,
            "name": "API Key revoke EMAIL",
            "subject": "We revoked your API key | Nous avons révoqué votre clé API",
            "content": apikey_revoke_limit_content,
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
                "normal",
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
                "normal",
            )
        )


def downgrade():
    op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(apikey_revoke_template_id))
    op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(apikey_revoke_template_id))
    op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(apikey_revoke_template_id))
    op.execute("DELETE FROM templates_history WHERE id = '{}'".format(apikey_revoke_template_id))
    op.execute("DELETE FROM templates WHERE id = '{}'".format(apikey_revoke_template_id))

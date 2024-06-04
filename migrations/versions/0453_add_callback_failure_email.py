"""
Revision ID: 0453_add_callback_failure_email
Revises: 0452_set_pgaudit_config
Create Date: 2024-06-04 16:09:00
"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0453_add_callback_failure_email"
down_revision = "0452_set_pgaudit_config"

callback_failure_template_id = current_app.config["CALLBACK_FAILURE_TEMPLATE_ID"]

def upgrade():
    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    callback_failure_content = "\n".join(
        [
            "[[fr]]",
            "(la version française suit)",
            "[[/fr]]",
            "",
            "[[en]]",
            "Hello ((name)),",
            "",
            "The callbacks for “((service_name))” are not working.  This could mean that:",
            "",
            "(1) Your callback service is down.",
            "(2) Your service is using a proxy that we cannot access.",
            "(3) We’re able to reach your service, but it responds with errors.",
            "",
            "It’s important to check your callback service is running, check your callback service’s logs for errors and repair any errors in your logs. Once you’ve taken these steps, request confirmation that your callbacks are working again by contacting us.",
            "",
            "The GC Notify team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Bonjour ((name)),",
            "",
            "Les rappels pour « ((service_name)) » ne fonctionnent pas. Cela pourrait signifier que :"
            "",
            "Votre service de rappel est hors service.",
            "Votre service utilise un proxy auquel nous ne pouvons pas accéder.",
            "Nous parvenons à joindre votre service, mais il répond avec des erreurs.",
            "Il est important de vérifier que votre service de rappel fonctionne, de consulter les journaux de votre service de rappel pour y détecter des erreurs et de corriger les erreurs dans vos journaux. Une fois ces étapes effectuées, veuillez demander une confirmation que vos rappels fonctionnent à nouveau en nous contactant.",
            "",
            "L’équipe GC Notify",
            "[[/fr]]",
        ]
    )

    templates = [
        {
            "id": callback_failure_template_id,
            "name": "Callback failures EMAIL",
            "subject": "Your callbacks are not working | Vos rappels ne fonctionnent pas",
            "content": callback_failure_content,
        }
    ]

    for template in templates:
        op.execute(
            sqltext=template_insert.format(
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
    op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(callback_failure_template_id))
    op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(callback_failure_template_id))
    op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(callback_failure_template_id))
    op.execute("DELETE FROM templates_history WHERE id = '{}'".format(callback_failure_template_id))
    op.execute("DELETE FROM templates WHERE id = '{}'".format(callback_failure_template_id))
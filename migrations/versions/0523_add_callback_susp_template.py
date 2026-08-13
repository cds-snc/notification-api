"""
Revision ID: 0523_add_callback_susp_template
Revises: 0522_add_api_key_to_reports
Create Date: 2026-08-12

Add Notify template used when suspending a service's callbacks because they are not working.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0523_add_callback_susp_template"
down_revision = "0522_add_api_key_to_reports"

callback_suspended_template_id = current_app.config["SERVICE_CALLBACK_SUSPENDED_TEMPLATE_ID"]
template_ids = [callback_suspended_template_id]


def _template_content():
    return "\n".join(
        [
            "[[fr]]",
            "",
            "(la version française suit)",
            "",
            "[[/fr]]",
            "",
            "[[en]]",
            "Hello ((name)),",
            "",
            "We've suspended the callbacks for \"((service_name))\" because they're not working. This means that you will no longer receive any callbacks for your service.",
            "",
            "Follow these steps to remove the suspension:",
            "",
            "1. Find your callback configuration and [test it](https://notification.canada.ca/services/((service_id))/api/callbacks/delivery-status-callback)",
            "2. Repair any errors and reduce latency for your callback service",
            "3. Check that your callback service takes no more than 1 second to respond",
            "",
            "Once you've taken these steps, request to resume callbacks for your service by contacting us.",
            "",
            "For more information, you can also access our API documentation on callbacks.",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Bonjour ((name)),",
            "",
            "Nous avons suspendu les rappels pour « ((service_name)) » car ils ne fonctionnaient pas. Cela signifie que vous ne recevrez plus aucun rappel pour votre service.",
            "",
            "Pour annuler cette suspension, suivez les étapes suivantes :",
            "",
            "1. Trouvez votre configuration de rappel et [testez-la](https://notification.canada.ca/services/((service_id))/api/callbacks/delivery-status-callback)",
            "2. Réparez les éventuelles erreurs et réduisez la latence de votre service de rappel",
            "3. Vérifiez que votre service de rappel ne prend pas plus d'une seconde pour répondre",
            "",
            "Une fois que vous aurez suivi ces étapes, demandez à réactiver les rappels pour votre service en nous contactant.",
            "",
            "Pour plus de renseignements, vous pouvez également vous référer à notre documentation API concernant les fonctions de rappel.",
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
        "id": callback_suspended_template_id,
        "name": "Callbacks suspended | Rappels suspendus",
        "subject": "Callbacks suspended for ((service_name)) | Rappels suspendus pour ((service_name))",
        "content": _template_content(),
        "template_type": "email",
        "template_category_id": "1d8ce435-a7e5-431b-aaa2-a418bc4d14f9",
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
            template["subject"],
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

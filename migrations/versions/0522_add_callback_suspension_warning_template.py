"""
Revision ID: 0522_add_callback_suspension_warning_template
Revises: 0521_update_bounce_rate_warn
Create Date: 2026-07-30

Add Notify template used to warn service teams that callback delivery is being
temporarily auto-suspended with exponential backoff.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0522_add_callback_suspension_warning_template"
down_revision = "0521_update_bounce_rate_warn"

callback_suspension_warning_template_id = current_app.config["CALLBACK_SUSPENSION_WARNING_TEMPLATE_ID"]
template_ids = [callback_suspension_warning_template_id]


def _template_content():
    return "\n".join(
        [
            "[[fr]](la version française suit)[[/fr]]",
            "",
            "[[en]]",
            "Hello ((name)),",
            "",
            "The callbacks for \"((service_name))\" are not working. This could mean that:",
            "",
            "1. Your callback service is down.",
            "2. Your service is using a proxy that we cannot access.",
            "3. We can reach your service, but it responds with errors.",
            "",
            "To protect system health, we are temporarily pausing callback delivery while we retry with exponential backoff.",
            "",
            "Please confirm your callback service is running, review your callback service logs for errors, and repair them. Find your callback configuration and [test it](((delivery_status_callback_test_url_en))).",
            "",
            "Once you've taken these steps, confirm that your callbacks are working again by contacting us. For more information, you can also access our [API documentation on callbacks](https://documentation.notification.canada.ca/rest-api.html#callbacks).",
            "",
            "The GC Notify team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Bonjour ((name)),",
            "",
            "Les rappels ne fonctionnent pas pour « ((service_name)) ». Cela pourrait signifier trois choses :",
            "",
            "1. Votre service de rappel est en panne.",
            "2. Votre service utilise un proxy auquel nous ne pouvons pas accéder.",
            "3. Nous sommes en mesure de joindre votre service, mais ses réponses sont erronées.",
            "",
            "Pour protéger la santé de notre système, nous suspendons temporairement la livraison des rappels pendant que nous effectuons des tentatives selon une stratégie de reprise exponentielle.",
            "",
            "Il est important de vérifier le bon fonctionnement de votre service de rappels, d'examiner les journaux d'activité qui s'y rapportent pour y déceler d'éventuelles erreurs, et de réparer ces erreurs le cas échéant. Trouvez la configuration de votre service de rappels et [testez-la](((delivery_status_callback_test_url_fr))).",
            "",
            "Après cela, contactez-nous pour confirmer que vos rappels fonctionnent à nouveau. Pour plus de renseignements, vous pouvez également vous référer à notre [documentation API concernant les fonctions de rappel](https://documentation.notification.canada.ca/rest-api.html#callbacks).",
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
        "id": callback_suspension_warning_template_id,
        "name": "Callback warning | Avertissement de rappel",
        "subject": "Action required: callbacks for ((service_name)) are not working | Mesure requise : les rappels de ((service_name)) ne fonctionnent pas",
        "content": _template_content(),
        "template_type": "email",
        "template_category_id": "1d8ce435-a7e5-431b-aaa2-a418bc4d14f9",
    }
    escaped_content = template["content"].replace("'", "''")
    escaped_subject = template["subject"].replace("'", "''")

    op.execute(
        template_insert.format(
            template["id"],
            template["name"],
            template["template_type"],
            datetime.utcnow(),
            escaped_content,
            current_app.config["NOTIFY_SERVICE_ID"],
            escaped_subject,
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
            escaped_subject,
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
"""
Revision ID: 0524_update_callback_susp_word
Revises: 0523_add_callback_susp_template
Create Date: 2026-08-13

Update callback suspension template wording to clarify suspension reason.
"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0524_update_callback_susp_word"
down_revision = "0523_add_callback_susp_template"


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
            "Hello,",
            "",
            "We've suspended the callbacks for ((service_name)) due to repeated errors with your callback URL.",
            "This means that you will no longer receive any callbacks for your service.",
            "",
            "Follow these steps to remove the suspension:",
            "",
            "1. Find your callback configuration and [test it](((service_callback_url_en)))",
            "2. Repair any errors and reduce latency for your callback service",
            "3. Check that your callback service takes no more than 1 second to respond",
            "",
            "Once you've taken these steps, request to resume callbacks for your service by [contacting us](https://notification.canada.ca/contact).",
            "",
            "For more information, you can also access our [API documentation on callbacks](https://documentation.notification.canada.ca/en/callbacks.html).",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Bonjour,",
            "",
            "Nous avons suspendu les rappels pour ((service_name)) en raison d'erreurs répétées avec votre URL de rappel.",
            "Cela signifie que vous ne recevrez plus aucun rappel pour votre service.",
            "",
            "Pour annuler cette suspension, suivez les étapes suivantes :",
            "",
            "1. Trouvez votre configuration de rappel et [testez-la](((service_callback_url_fr)))",
            "2. Réparez les éventuelles erreurs et réduisez la latence de votre service de rappel",
            "3. Vérifiez que votre service de rappel ne prend pas plus d'une seconde pour répondre",
            "",
            "Une fois que vous aurez suivi ces étapes, demandez à réactiver les rappels pour votre service en nous [contactant](https://notification.canada.ca/fr/contact).",
            "",
            "Pour plus de renseignements, vous pouvez également vous référer à notre [documentation API concernant les fonctions de rappel](https://documentation.notification.canada.ca/fr/rappel.html).",
            "",
            "L'équipe Notification GC",
            "[[/fr]]",
        ]
    )


def upgrade():
    conn = op.get_bind()

    template_id = current_app.config["SERVICE_CALLBACK_SUSPENDED_TEMPLATE_ID"]

    current_version = conn.execute("select version from templates where id='{}'".format(template_id)).fetchone()
    name = conn.execute("select name from templates where id='{}'".format(template_id)).fetchone()
    current_category = conn.execute(
        "select template_category_id from templates where id='{}'".format(template_id)
    ).fetchone()

    new_version = (current_version[0] if current_version and current_version[0] is not None else 0) + 1
    template_name = name[0] if name else "Callbacks suspended | Rappels suspendus"
    template_category = current_category[0] if current_category is not None else None

    template_subject = "Action required: Callbacks suspended for ((service_name)) | Mesure requise: Rappels suspendus pour ((service_name))"
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

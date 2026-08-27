"""
Revision ID: 0504_fix_template_link
Revises: 0503_add_user_rte_default
Create Date: 2026-02-12 00:00:00

"""
from alembic import op
from flask import current_app
from datetime import datetime

revision = "0504_fix_template_link"
down_revision = "0503_add_user_rte_default"

template_id = current_app.config["SERVICE_NOW_LIVE_TEMPLATE_ID"]


def upgrade():
    conn = op.get_bind()

    # fetch current values
    current_version = conn.execute("select version from templates where id='{}'".format(template_id)).fetchone()
    name = conn.execute("select name from templates where id='{}'".format(template_id)).fetchone()
    current_category = conn.execute(
        "select template_category_id from templates where id='{}'".format(template_id)
    ).fetchone()

    new_version = current_version[0] + 1
    template_name = name[0]
    template_category = current_category[0] if current_category is not None else None

    template_subject = "Your service is now live | Votre service est maintenant activé"

    template_content = "\n".join(
        [
            "Hello ((name)),",
            "",
            "",
            "((service_name)) is now live on GC Notify.",
            "",
            "You’re all set to send notifications outside your team.",
            "",
            "",
            "You can send up to ((message_limit_en)) messages per day.",
            "",
            "If you ever need to send more messages, [contact us](((contact_us_url))).",
            "",
            "",
            "[Sign in to GC Notify](((signin_url)))",
            "",
            "___",
            "",
            "Bonjour ((name)),",
            "",
            "",
            "((service_name)) est maintenant activé sur GC Notification.",
            "",
            "Vous êtes prêts à envoyer des notifications en dehors de votre équipe.",
            "",
            "",
            "Vous pouvez envoyer jusqu’à ((message_limit_fr)) messages par jour.",
            "",
            "Si jamais vous avez besoin d’envoyer plus de messages, [communiquez avec nous](((contact_us_url))).",
            "",
            "",
            "[Connectez-vous à GC Notification](((signin_url)))",
        ]
    )

    escaped_content = template_content.replace("'", "''")
    escaped_subject = template_subject.replace("'", "''") if template_subject is not None else None
    escaped_name = template_name.replace("'", "''") if template_name is not None else None

    # update templates row with new content and incremented version
    if template_category is not None:
        op.execute(
            "UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}', template_category_id = '{}' WHERE id = '{}'".format(
                escaped_content,
                escaped_subject if escaped_subject is not None else "",
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
                escaped_subject if escaped_subject is not None else "",
                new_version,
                datetime.utcnow(),
                template_id,
            )
        )

    # insert new row into templates_history to keep previous versions
    # prepare category value for SQL: quote UUIDs, use NULL when missing
    if template_category is not None and template_category != "":
        template_category_sql = "'{}'".format(template_category)
    else:
        template_category_sql = "NULL"

    op.execute(
        "INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject, created_by_id, version, hidden, template_category_id) VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, false, {})".format(
            template_id,
            escaped_name if escaped_name is not None else "",
            "email",
            datetime.utcnow(),
            escaped_content,
            current_app.config["NOTIFY_SERVICE_ID"],
            escaped_subject if escaped_subject is not None else "",
            current_app.config["NOTIFY_USER_ID"],
            new_version,
            template_category_sql,
        )
    )


def downgrade():
    pass

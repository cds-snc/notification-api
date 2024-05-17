"""

Revision ID: 0448_update_verify_code2
Revises: 0449_update_magic_link_auth
Create Date: 2023-10-05 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0449_update_magic_link_auth"
down_revision = "0448_update_verify_code2"

near_content = "\n".join(
    [
        "[[en]]"
        "Hi ((name)),"
        ""
        "Here is your magic link to log in to GC Notify:"
        ""
        "^ **[Sign-in](((link_url_en)))**"
        "[[/en]]"
        ""
        "---"
        ""
        "[[fr]]"
        "Bonjour ((name)),"
        ""
        "Voici votre lien magique pour vous connecter à Notification GC:"
        ""
        "^ **[Connectez-vous](((link_url_fr)))**"
        "[[/fr]]"
    ]
)


template = {
    "id": current_app.config["EMAIL_MAGIC_LINK_TEMPLATE_ID"],
    "template_type": "email",
    "subject": "Sign in | Connectez-vous",
    "content": near_content,
    "process_type": "priority",
    "name": "Sign in - Magic Link | Se connecter - Lien magique",
}


def upgrade():
    conn = op.get_bind()

    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, updated_at, content, service_id, subject, created_by_id, version, archived, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', false, '{}', false)
    """

    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, '{}', false)
    """
    op.execute(
        template_insert.format(
            template["id"],
            template["name"],
            template["template_type"],
            datetime.utcnow(),
            datetime.utcnow(),
            template["content"],
            current_app.config["NOTIFY_SERVICE_ID"],
            template["subject"],
            current_app.config["NOTIFY_USER_ID"],
            1,
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
            1,
            template["process_type"],
        )
    )

    op.execute("INSERT INTO auth_type (name) VALUES ('magic_link')")


def downgrade():
    op.execute("DELETE FROM auth_type WHERE name = 'magic_link'")

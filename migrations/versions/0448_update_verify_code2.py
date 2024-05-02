"""

Revision ID: 0448_update_verify_code2
Revises: 0447_update_verify_code_template
Create Date: 2023-10-05 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0448_update_verify_code2"
down_revision = "0447_update_verify_code_template"

near_content = "\n".join(
    [
        "[[en]]",
        "Hi ((name)),",
        "",
        "Here is your security code to log in to GC Notify:",
        "",
        "^ ((verify_code))",
        "[[/en]]",
        "",
        "---",
        "",
        "[[fr]]",
        "Bonjour ((name)),",
        "",
        "Voici votre code de sécurité pour vous connecter à Notification GC:",
        "",
        "^ ((verify_code))",
        "[[/fr]]",
    ]
)


templates = [
    {
        "id": current_app.config["EMAIL_2FA_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "Sign in | Connectez-vous",
        "content": near_content,
        "process_type": "priority",
    },
]


def upgrade():
    conn = op.get_bind()

    for template in templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        name = conn.execute("select name from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1
        template["name"] = name[0]

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

"""

Revision ID: 0493_update_user_deact_tmpl
Revises: 0492_add_service_del_template
Create Date: 2025-11-10 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0493_update_user_deact_tmpl"
down_revision = "0492_add_service_del_template"


def _new_user_deactivated_content():
    return "\n".join(
        [
            "[[fr]](la version française suit)[[/fr]]",
            "",
            "[[en]]",
            "You’ve deactivated your GC Notify account.",
            "",
            "You cannot:",
            "- Access GC Notify services.",
            "- Manage teams or make changes on GC Notify.",
            "",
            "If you did not want to deactivate your account, immediately [contact us](https://notification.canada.ca/en/contact).",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Vous avez désactivé votre compte Notification GC.",
            "",
            "Vous ne pouvez plus :",
            "- Accéder aux services Notification GC.",
            "- Gérer des équipes ou apporter des modifications dans Notification GC.",
            "",
            "En cas de désactivation involontaire de votre compte, [contactez-nous](https://notification.canada.ca/fr/contact) immédiatement.",
            "",
            "L’équipe Notification GC",
            "[[/fr]]",
        ]
    )


def upgrade():
    conn = op.get_bind()

    template_id = current_app.config["USER_DEACTIVATED_TEMPLATE_ID"]

    # get current version and bump
    current_version = conn.execute("select version from templates where id='{}'".format(template_id)).fetchone()
    new_version = (current_version[0] if current_version and current_version[0] is not None else 0) + 1

    new_content = _new_user_deactivated_content()
    new_subject = "Account closed | Votre compte a été désactivé"

    op.execute(
        """
        UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}'
        WHERE id = '{}'
    """.format(new_content, new_subject, new_version, datetime.utcnow(), template_id)
    )

    op.execute(
        """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, '{}', false)
    """.format(
            template_id,
            "User deactivated",
            "email",
            datetime.utcnow(),
            new_content,
            current_app.config["NOTIFY_SERVICE_ID"],
            new_subject,
            current_app.config["NOTIFY_USER_ID"],
            new_version,
            "normal",
        )
    )


def downgrade():
    pass
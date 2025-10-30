"""

Revision ID: 0491_split_deactivate_templates
Revises: 0490_add_service_susp_template
Create Date: 2025-10-28 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0491_split_deactivate_templates"
down_revision = "0490_add_service_susp_template"

# IDs from config
service_suspended_template_id = current_app.config["SERVICE_SUSPENDED_TEMPLATE_ID"]
user_deactivated_template_id = current_app.config["USER_DEACTIVATED_TEMPLATE_ID"]


def _new_service_suspended_content():
    return "\n".join(
        [
            "[[fr]](la version française suit)[[/fr]]",
            "",
            "[[en]]",
            "We’ve suspended ((service_name)) because you’re now the only team member for that service. The other team member deactivated their account.",
            "",
            "GC Notify requires at least 2 team members per service.",
            "",
            "To remove the suspension, we need:",
            "- Suspended service’s name",
            "- Name of a new team member who already has a GC Notify account.",
            "",
            "When you have this information, [contact us](https://notification.canada.ca/en/contact).",
            "",
            "The GC Notify Team",
            "[[/en]]",
            "",
            "---",
            "",
            "[[fr]]",
            "Nous avons suspendu le service ((service_name)) parce que vous êtes maintenant la seule personne affectée à ce service. Les autres membres de l’équipe ont désactivé leur compte.",
            "",
            "Notification GC exige qu’au moins 2 personnes soient affectées à un service.",
            "",
            "Pour rétablir le service, il faudra nous faire parvenir les éléments suivants :",
            "- Le nom du service suspendu",
            "- Le nom d’un nouveau membre d’équipe qui a déjà un compte Notification GC.",
            "",
            "Lorsque vous aurez ces renseignements en main, [contactez-nous](https://notification.canada.ca/fr/contact).",
            "",
            "L’équipe Notification GC",
            "[[/fr]]",
        ]
    )


def _new_user_deactivated_content():
    # content from the previous migration 0490 which should now be moved to USER_DEACTIVATED_TEMPLATE_ID
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
            "Vous avez désactivé votre compte GC Notify.",
            "",
            "Vous ne pouvez plus :",
            "- Accéder aux services GC Notify ;",
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

    # prepare templates to update/insert
    templates_to_update = [
        {
            "id": service_suspended_template_id,
            "name": "Service suspended",
            "template_type": "email",
            "content": _new_service_suspended_content(),
            "subject": "Service suspended | Service suspendu",
            "process_type": "normal",
        }
    ]

    templates_to_insert = [
        {
            "id": user_deactivated_template_id,
            "name": "User deactivated",
            "template_type": "email",
            "content": _new_user_deactivated_content(),
            "subject": "Account closed | Compte fermé",
            "process_type": "normal",
        }
    ]

    # bump versions for updates
    for t in templates_to_update:
        current_version = conn.execute("select version from templates where id='{}'".format(t["id"])).fetchone()
        t["version"] = (current_version[0] if current_version and current_version[0] is not None else 0) + 1

    template_update = """
        UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}'
        WHERE id = '{}'
    """

    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, '{}', false)
    """

    # perform updates
    for t in templates_to_update:
        op.execute(
            template_update.format(
                t["content"],
                t["subject"],
                t["version"],
                datetime.utcnow(),
                t["id"],
            )
        )

        op.execute(
            template_history_insert.format(
                t["id"],
                t["name"],
                t["template_type"],
                datetime.utcnow(),
                t["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                t["subject"],
                current_app.config["NOTIFY_USER_ID"],
                t["version"],
                t["process_type"],
            )
        )

    # insert new template for user_deactivated
    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    template_history_insert_simple = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    for t in templates_to_insert:
        op.execute(
            template_insert.format(
                t["id"],
                t["name"],
                t["template_type"],
                datetime.utcnow(),
                t["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                t["subject"],
                current_app.config["NOTIFY_USER_ID"],
                t["process_type"],
            )
        )

        op.execute(
            template_history_insert_simple.format(
                t["id"],
                t["name"],
                t["template_type"],
                datetime.utcnow(),
                t["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                t["subject"],
                current_app.config["NOTIFY_USER_ID"],
                t["process_type"],
            )
        )


def downgrade():
    # remove both the user_deactivated template and the service_suspended template
    for template_id in (user_deactivated_template_id, service_suspended_template_id):
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

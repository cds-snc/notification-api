"""

Revision ID: 0489_update_template_wording
Revises: 0488_update_2fa_templates
Create Date: 2025-09-15 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0489_update_template_wording"
down_revision = "0488_update_2fa_templates"

CAT_AUTH_ID = "b6c42a7e-2a26-4a07-802b-123a5c3198a9"

templates = [
    {
        "id": current_app.config["FORCED_PASSWORD_RESET_TEMPLATE_ID"],
        "template_type": "email",
        "category_id": CAT_AUTH_ID,
        "subject": "Reset your password | Réinitialiser votre mot de passe",
        "content": """[[fr]]
(la version française suit)
[[/fr]]

[[en]]
Hi ((user_name)),

To reset your password, use this link:

[Password reset](((url))?lang=en)

This is your unique link. Do not share this link with anyone.

 If GC Notify did not prompt you to change your password [contact us](https://notification.canada.ca/contact?lang=en).
[[/en]]

For details about the password change, read [incidents and service interruptions](https://notification.canada.ca/system-status#h-incidents-and-service-interruptions).

___

[[fr]]
Bonjour ((user_name)),

Pour réinitialiser votre mot de passe, utilisez ce lien :

[Réinitialisation de votre mot de passe](((url))?lang=fr)

Ce lien est unique. Ne le transmettez à personne. 

Si Notification GC ne vous a pas invité·e à changer votre mot de passe, [nous contacter](https://notification.canada.ca/contact?lang=fr).
[[/fr]]

Pour plus de détails sur le changement de mot de passe, lisez [Incidents et interruptions de service](https://notification.canada.ca/etat-du-systeme#h-incidents-et-interruptions-de-service).""",
    },
    {
        "id": current_app.config["PASSWORD_RESET_TEMPLATE_ID"],
        "template_type": "email",
        "category_id": CAT_AUTH_ID,
        "subject": "Reset your password | Réinitialiser votre mot de passe",
        "content": """[[en]]
Hi ((user_name)),

We received a request to reset your password on GC Notify.

If you didn't request this email, you can ignore it – your password has not been changed.

To reset your password, use this link:
[Password reset](((url)) ""Password reset"")
[[/en]]

___

[[fr]]
Bonjour ((user_name)),

Nous avons reçu une demande de réinitialisation de votre mot de passe dans Notification GC.

Si vous n'avez pas demandé ce courriel, vous pouvez l'ignorer - votre mot de passe n'a pas été changé.

Pour réinitialiser votre mot de passe, utilisez ce lien :
[Réinitialisation du mot de passe](((url)) ""Réinitialisation du mot de passe"")
[[/fr]]""",
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
        UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}', template_category_id = '{}'
        WHERE id = '{}'
    """
    template_update_no_subject = """
        UPDATE templates SET content = '{}', version = '{}', updated_at = '{}', template_category_id = '{}'
        WHERE id = '{}'
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, hidden, template_category_id)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, false, '{}')
    """

    for template in templates:
        escaped_content = template["content"].replace("'", "''")
        escaped_subject = template["subject"].replace("'", "''") if template["subject"] is not None else None
        
        if template["subject"] is not None:
            op.execute(
                template_update.format(
                    escaped_content,
                    escaped_subject,
                    template["version"],
                    datetime.utcnow(),
                    template["category_id"],
                    template["id"],
                )
            )
        else:
            op.execute(
                template_update_no_subject.format(
                    escaped_content,
                    template["version"],
                    datetime.utcnow(),
                    template["category_id"],
                    template["id"],
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
                escaped_subject if escaped_subject is not None else "",
                current_app.config["NOTIFY_USER_ID"],
                template["version"],
                template["category_id"],
            )
        )
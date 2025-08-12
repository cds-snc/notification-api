"""

Revision ID: 0488_update_2fa_templates
Revises: 0487_update_user_auth_constraint
Create Date: 2025-08-12 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0488_update_2fa_templates"
down_revision = "0487_update_user_auth_constraint"


templates = [
    {
        "id": current_app.config["ACCOUNT_CHANGE_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "Account information changed | Renseignements de compte modifiés",
        "content": """[[fr]]
*(la version française suit)*
[[/fr]]

[[en]]
You just made one or more changes to your [GC Notify](((base_url))) account:

((change_type_en))

**If you did not make this change**, immediately [contact us](https://notification.canada.ca/contact?lang=en).
[[/en]]

___

[[fr]]
Vous avez effectué une ou plusieurs modifications dans votre profil [Notification GC](((base_url))) :

((change_type_fr))

**Si vous n'avez pas effectué ces modifications**, veuillez [nous joindre](https://notification.canada.ca/contact?lang=fr) immédiatement.
[[/fr]]""",
    },
    {
        "id": current_app.config["EMAIL_MAGIC_LINK_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "Sign in | Connectez-vous",
        "content": """[[fr]]
*(la version française suit)*
[[/fr]]

[[en]]
Hello ((name))

Sign in to GC Notify with the following magic link: 

^ [Sign in](((link_url_en)))

The GC Notify Team
[[/en]]
---
[[fr]]
Bonjour ((name)),

Connectez-vous à Notification GC à l'aide du lien magique :

^ [Connectez-vous](((link_url_fr)))

L'équipe Notification GC
[[/fr]]""",
    },
    {
        "id": current_app.config["NEW_USER_EMAIL_VERIFICATION_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "Confirm your registration | Confirmer votre inscription",
        "content": """[[fr]]
*(la version française suit)*
[[/fr]]

[[en]]
Hello ((name))

Complete your registration for GC Notify by selecting the following link: 
((url))

The GC Notify Team
[[/en]]

---

[[fr]]
Bonjour ((name)),

Pour terminer votre inscription à Notification GC, utilisez le lien suivant : 
((url))

L'équipe Notification GC
[[/fr]]""",
    },
    {
        "id": current_app.config["EMAIL_2FA_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "Sign in | Connectez-vous",
        "content": """[[fr]]
*(la version française suit)*
[[/fr]]

[[en]]
Hello ((name))

Finish signing in to GC Notify by entering the following code:

^ ((verify_code))

The GC Notify Team
[[/en]]

---

[[fr]]
Bonjour ((name)),

Terminez votre connexion à Notification GC en saisissant le code de sécurité suivant :

^ ((verify_code))

L'équipe Notification GC
[[/fr]]""",
    },
    {
        "id": current_app.config["SMS_CODE_TEMPLATE_ID"],
        "template_type": "sms",
        "subject": None,
        "content": "((verify_code)) is your GC Notify authentication code | ((verify_code)) est votre code d'authentification de Notification GC",
    },
    {
        "id": current_app.config["CHANGE_EMAIL_CONFIRMATION_TEMPLATE_ID"],
        "template_type": "email",
        "subject": "Confirm new email address | Confirmer votre nouvelle adresse courriel",
        "content": """[[fr]]
*(la version française suit)*
[[/fr]]

[[en]]
Hello ((name))

Confirm your new email address with GC Notify by selecting the following link: ((url))
        
**If you did not change your email address**, [contact us](
((feedback_url)) ""contact us"").

The GC Notify Team
[[/en]]
---
[[fr]]
Bonjour ((name)),

Confirmez votre nouvelle adresse courriel pour Notification GC à l'aide du lien suivant : 
((url))
        
**Si vous n'avez pas effectué cette modification**, veuillez [nous joindre](((feedback_url)) ""communiquez avec nous"").

L'équipe Notification GC
[[/fr]]""",
    },
]


def upgrade():
    conn = op.get_bind()

    for template in templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        name = conn.execute("select name from templates where id='{}'".format(template["id"])).fetchone()
        process_type = conn.execute("select process_type from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1
        template["name"] = name[0]
        template["process_type"] = process_type[0]

    template_update = """
        UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}'
        WHERE id = '{}'
    """
    template_update_no_subject = """
        UPDATE templates SET content = '{}', version = '{}', updated_at = '{}'
        WHERE id = '{}'
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, '{}', false)
    """

    for template in templates:
        if template["subject"] is not None:
            op.execute(
                template_update.format(
                    template["content"],
                    template["subject"],
                    template["version"],
                    datetime.utcnow(),
                    template["id"],
                )
            )
        else:
            op.execute(
                template_update_no_subject.format(
                    template["content"],
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
                template["subject"] if template["subject"] is not None else "",
                current_app.config["NOTIFY_USER_ID"],
                template["version"],
                template["process_type"],
            )
        )


def downgrade():
    pass

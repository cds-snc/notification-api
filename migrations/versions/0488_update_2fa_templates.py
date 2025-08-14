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

CAT_AUTH_ID = "b6c42a7e-2a26-4a07-802b-123a5c3198a9"
CAT_AUTO_ID = "977e2a00-f957-4ff0-92f2-ca3286b24786"

templates = [
    {
        "id": current_app.config["ACCOUNT_CHANGE_TEMPLATE_ID"],
        "template_type": "email",
        "category_id": CAT_AUTO_ID,
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
        "category_id": CAT_AUTH_ID,
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
        "category_id": CAT_AUTH_ID,
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
        "category_id": CAT_AUTH_ID,
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
        "category_id": CAT_AUTH_ID,
        "subject": None,
        "content": "((verify_code)) is your GC Notify authentication code | ((verify_code)) est votre code d'authentification de Notification GC",
    },
    {
        "id": current_app.config["CHANGE_EMAIL_CONFIRMATION_TEMPLATE_ID"],
        "template_type": "email",
        "category_id": CAT_AUTO_ID,
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
        # Escape single quotes in content and subject for SQL
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
                    auth_template_category_id,
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
                auth_template_category_id,
            )
        )


def downgrade():
    pass

"""empty message

Revision ID: 0419_add_forced_pass_template
Revises: 0327_add_password_expired
Create Date: 2022-04-19 13:00:00

"""

import uuid

# revision identifiers, used by Alembic.
from datetime import datetime

from alembic import op

from app.encryption import hashpw

revision = "0419_add_forced_pass_template"
down_revision = "0327_add_password_expired"


user_id = "6af522d0-2915-4e52-83a3-3690455a5fe6"
service_id = "d6aa2c68-a2d9-4437-ab19-3ae8eb202553"


def upgrade():
    op.get_bind()
    template_insert = """INSERT INTO templates (id, name, template_type, created_at,
                                                content, archived, service_id, subject, created_by_id, version, process_type, hidden)
                                 VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', False)
                              """

    template_history_insert = """INSERT INTO templates_history (id, name, template_type, created_at,
                                                                content, archived, service_id,
                                                                subject, created_by_id, version, process_type, hidden)
                                 VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, 'normal', False)
                            """

    password_reset_content = """
        Hi ((Name)),
        To reset your password, click this link:
        [Password reset](((url))?lang=en)
        This is your unique link. Do not share this link with anyone.
        If you didnt request this email, please [contact us](https://notification.canada.ca/contact?lang=en).
        ___
        Bonjour ((Name)),
        Pour réinitialiser votre mot de passe, veuillez cliquer sur le lien suivant :
        [Réinitialisation de votre mot de passe](((url))?lang=fr)
        Ce lien est unique. Ne le transmettez à personne. 
        Si vous navez pas demandé ce courriel, veuillez [nous contacter](https://notification.canada.ca/contact?lang=fr).
        """

    op.execute(
        template_history_insert.format(
            "e9a65a6b-497b-42f2-8f43-1736e43e13b3",
            "Notify forced-password reset email",
            "email",
            datetime.utcnow(),
            password_reset_content,
            service_id,
            "Force reset your Notify password",
            user_id,
        )
    )

    op.execute(
        template_insert.format(
            "e9a65a6b-497b-42f2-8f43-1736e43e13b3",
            "Notify forced-password reset email",
            "email",
            datetime.utcnow(),
            password_reset_content,
            service_id,
            "Force reset your Notify password",
            user_id,
            "normal",
        )
    )


def downgrade():
    op.get_bind()
    op.execute("delete from templates where id = '{}'".format("e9a65a6b-497b-42f2-8f43-1736e43e13b3"))
    op.execute("delete from templates_history where id = '{}'".format("e9a65a6b-497b-42f2-8f43-1736e43e13b3"))

"""empty message

Revision ID: 0301c_update_golive_template
Revises: 0301b_fido2_table
Create Date: 2019-08-13 07:42:00.0000

"""

# revision identifiers, used by Alembic.
from datetime import datetime

from flask import current_app

from alembic import op
import sqlalchemy as sa

revision = '0301c_update_golive_template'
down_revision = '0301b_fido2_table'


def upgrade():
    template_content = """Hi ((name)),

    ((service name)) is now live on Notification.

    You can send up to ((message limit)) messages per day.

    If you have a question, or something goes wrong, please contact us:
    https://notification.cdssandbox.xyz/support/ask-question-give-feedback

    We’ll reply as soon as possible.

    Thank you from the Notification team.

    -

    Salute ((name)),

    ((service name)) est maintenant actif sur Notification.

    Vous pouvez envoyer jusqu’à ((message limit)) messages chaque jour.

    Si vous avez une question ou un problème, envoyons-nous un courriel:
    https://notification.cdssandbox.xyz/support/ask-question-give-feedback

    Nous vous répondrons bientôt.

    Merci,
    L’équipe de notification.
    """
    template_subject = '((service name)) is now live on Notification'

    update = """
    UPDATE
        {}
    SET
        content = '{}',
        subject = '{}'
    WHERE
        id = '618185c6-3636-49cd-b7d2-6f6f5eb3bdde'
    """

    op.execute(
        update.format('templates', template_content, template_subject)
    )

    op.execute(
        update.format('templates_history', template_content, template_subject)
    )


def downgrade():
    pass

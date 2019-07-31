"""

Revision ID: 0300d_update_invite_email
Revises: 0300c_remove_email_branding
Create Date: 2019-07-29 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = '0300d_update_invite_email'
down_revision = '0300c_remove_email_branding'

from alembic import op
import sqlalchemy as sa


def upgrade():

    op.execute("""
            UPDATE
                templates
            SET
                content = 
                  REPLACE(
                    content,
                    'Click this link to create an account on Notification',
                    'Use this link to accept the invitation'
                  )
            WHERE
                id = '4f46df42-f795-4cc4-83bb-65ca312f49cc'
        """)

    op.execute("""
            UPDATE
                templates_history
            SET
                content = 
                  REPLACE(
                    content,
                    'Click this link to create an account on Notification',
                    'Use this link to accept the invitation'
                  )
            WHERE
                id = '4f46df42-f795-4cc4-83bb-65ca312f49cc'
        """)


def downgrade():
    pass
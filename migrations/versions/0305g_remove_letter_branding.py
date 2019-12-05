"""

Revision ID: 0305g_remove_letter_branding
Revises: 0305f_sending_domain_for_service
Create Date: 2019-12-05 17:08:21.019759

"""
import sqlalchemy as sa
from alembic import op

revision = '0305g_remove_letter_branding'
down_revision = '0305f_sending_domain_for_service'

def upgrade():
    op.get_bind()
    op.execute("DELETE FROM letter_branding")

def downgrade():
    pass

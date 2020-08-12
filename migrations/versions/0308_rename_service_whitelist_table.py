"""

Revision ID: 0308_rename_service_whitelist
Revises: 0307_update_email_2fa_template
Create Date: 2020-08-04 12:50:00

"""
from alembic import op


revision = '0308_rename_service_whitelist'
down_revision = '0307_update_email_2fa_template'


def upgrade():
    op.execute('ALTER TABLE service_whitelist RENAME TO service_safelist')

def downgrade():
    op.execute('ALTER TABLE service_safelist RENAME TO service_whitelist')

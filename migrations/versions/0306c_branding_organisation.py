"""

Revision ID: 0306c_branding_organisation
Revises: 0306b_branding_french_fip
Create Date: 2020-05-19 09:30:00

"""
from alembic import op


revision = '0306c_branding_organisation'
down_revision = '0306b_branding_french_fip'


def upgrade():
    op.execute('ALTER TABLE organisation ADD COLUMN default_branding_is_french boolean DEFAULT false')

def downgrade():
    op.execute('ALTER TABLE organisation DROP COLUMN default_branding_is_french')
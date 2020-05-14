"""

Revision ID: 0306b_branding_french_fip
Revises: 0306a_branding_variables_fix
Create Date: 2020-05-07 14:00:00

"""
from alembic import op


revision = '0306b_branding_french_fip'
down_revision = '0306a_branding_variables_fix'


def upgrade():
    op.execute("INSERT INTO branding_type VALUES ('both_english'), ('both_french')")
    op.execute("UPDATE email_branding SET brand_type = 'both_english' WHERE brand_type = 'both'")
    op.execute("DELETE FROM branding_type WHERE name = 'both'")

    op.execute('ALTER TABLE services ADD COLUMN default_branding_is_french boolean DEFAULT false')
    op.execute('ALTER TABLE services_history ADD COLUMN default_branding_is_french boolean DEFAULT false')

def downgrade():
    op.execute("INSERT INTO branding_type VALUES ('both')")
    op.execute("UPDATE email_branding SET brand_type = 'both' WHERE brand_type = 'both_english'")
    op.execute("UPDATE email_branding SET brand_type = 'both' WHERE brand_type = 'both_french'")
    op.execute("DELETE FROM branding_type WHERE name = 'both_english'")
    op.execute("DELETE FROM branding_type WHERE name = 'both_french'")

    op.execute('ALTER TABLE services DROP COLUMN default_branding_is_french')
    op.execute('ALTER TABLE services_history DROP COLUMN default_branding_is_french')
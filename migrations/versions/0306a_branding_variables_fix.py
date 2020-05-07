"""

Revision ID: 0306a_branding_variables_fix
Revises: 0306_branding_variables_rename
Create Date: 2020-05-07 11:48:00

"""
from alembic import op


revision = '0306a_branding_variables_fix'
down_revision = '0306_branding_variables_rename'


def upgrade():
    op.execute("INSERT INTO branding_type (name) VALUES ('custom_logo_with_background_colour')")
    op.execute("UPDATE email_branding SET brand_type = 'custom_logo_with_background_colour' WHERE brand_type = 'custom_logo_with_banner'")
    op.execute("DELETE FROM branding_type WHERE name = 'custom_logo_with_banner'")

def downgrade():
    op.execute("INSERT INTO branding_type (name) VALUES ('custom_logo_with_banner')")
    op.execute("UPDATE email_branding SET brand_type = 'custom_logo_with_banner' WHERE brand_type = 'custom_logo_with_background_colour'")
    op.execute("DELETE FROM branding_type WHERE name = 'custom_logo_with_background_colour'")
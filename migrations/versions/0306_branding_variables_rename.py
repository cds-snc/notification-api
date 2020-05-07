"""

Revision ID: 0306_branding_variables_rename
Revises: 0305m_add_pinpoint
Create Date: 2020-05-06 10:44:00

"""
from alembic import op


revision = '0306_branding_variables_rename'
down_revision = '0305m_add_pinpoint'


def upgrade():
    op.execute("INSERT INTO branding_type (name) VALUES ('custom_logo'), ('custom_logo_with_banner')")
    op.execute("UPDATE email_branding SET brand_type = 'custom_logo' WHERE brand_type = 'org'")
    op.execute("UPDATE email_branding SET brand_type = 'custom_logo_with_banner' WHERE brand_type = 'org_banner'")
    op.execute("DELETE FROM branding_type WHERE name = 'org_banner'")
    op.execute("DELETE FROM branding_type WHERE name = 'org'")

def downgrade():
    op.execute("INSERT INTO branding_type (name) VALUES ('org'), ('org_banner')")
    op.execute("UPDATE email_branding SET brand_type = 'org' WHERE brand_type = 'custom_logo'")
    op.execute("UPDATE email_branding SET brand_type = 'org_banner' WHERE brand_type = 'custom_logo_with_banner'")
    op.execute("DELETE FROM branding_type WHERE name = 'custom_logo'")
    op.execute("DELETE FROM branding_type WHERE name = 'custom_logo_with_banner'")
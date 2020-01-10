"""

Revision ID: 0305j_add_branding_option
Revises: 0305i_add_pii_failed_status
Create Date: 2020-01-02 11:24:58.773824

"""
from alembic import op


revision = '0305j_add_branding_option'
down_revision = '0305i_add_pii_failed_status'


def upgrade():
    op.execute("INSERT INTO branding_type (name) VALUES ('no_branding')")


def downgrade():
    op.execute("DELETE FROM branding_type WHERE name = 'no_branding'")

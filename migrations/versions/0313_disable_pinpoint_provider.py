"""

Revision ID: 0313_disable_pinpoint_provider
Revises: 0312_update_branding_request
Create Date: 2021-01-08 09:03:00 .214680

"""
from alembic import op


revision = '0313_disable_pinpoint_provider'
down_revision = '0312_update_branding_request'


def upgrade():
    op.execute("UPDATE provider_details set active=false where identifier in ('pinpoint');")


def downgrade():
    op.execute("UPDATE provider_details set active=true where identifier in ('pinpoint');")

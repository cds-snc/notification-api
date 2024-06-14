"""

Revision ID: 0450_enable_pinpoint_provider
Revises: 0449_update_magic_link_auth
Create Date: 2021-01-08 09:03:00 .214680

"""
from alembic import op

revision = "0450_enable_pinpoint_provider"
down_revision = "0449_update_magic_link_auth"


def upgrade():
    op.execute("UPDATE provider_details set active=true where identifier in ('pinpoint');")


def downgrade():
    op.execute("UPDATE provider_details set active=false where identifier in ('pinpoint');")

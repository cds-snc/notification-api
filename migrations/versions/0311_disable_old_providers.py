"""

Revision ID: 0311_disable_old_providers
Revises: 0310_account_change_type
Create Date: 2020-10-13 20:33:50.214680

"""
from alembic import op
import sqlalchemy as sa


revision = '0311_disable_old_providers'
down_revision = '0310_account_change_type'


def upgrade():
    op.execute("UPDATE provider_details set active=false where identifier in ('loadtesting', 'firetext', 'mmg');")


def downgrade():
    op.execute("UPDATE provider_details set active=true where identifier in ('loadtesting', 'firetext', 'mmg');")

"""
Revision ID: 0358_default_send_field
Revises: 0357_promoted_templates_table
Create Date: 2023-05-19 18:21:53.942613
"""

from alembic import op
import sqlalchemy as sa

revision = "0358_default_send_field"
down_revision = "0357_promoted_templates_table"


def upgrade():
    op.add_column("communication_items", sa.Column("default_send_indicator", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("communication_items", "default_send_indicator")

"""
Revision ID: 0461_add_rtl_column_templates
Revises: 0460_new_service_columns
Create Date: 2024-06-27 13:32:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0461_add_rtl_column_templates"
down_revision = "0460_new_service_columns"


def upgrade():
    # Add the new column to the templates table
    op.add_column("templates", sa.Column("text_direction_rtl", sa.Boolean(), nullable=False, server_default=sa.false()))

    # Add the new column to the templates_history table
    op.add_column("templates_history", sa.Column("text_direction_rtl", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    # Remove the column from the templates table
    op.drop_column("templates", "text_direction_rtl")

    # Remove the column from the templates_history table
    op.drop_column("templates_history", "text_direction_rtl")

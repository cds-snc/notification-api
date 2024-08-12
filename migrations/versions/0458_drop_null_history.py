"""
Revision ID: 0458_drop_null_history
Revises: 0457_update_categories
Create Date: 2024-06-25 13:32:00
"""
from alembic import op

revision = "0458_drop_null_history"
down_revision = "0457_update_categories"


def upgrade():
    op.alter_column("templates_history", "process_type", nullable=True)


def downgrade():
    op.alter_column("templates_history", "process_type", nullable=False)

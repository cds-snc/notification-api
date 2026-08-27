"""
Revision ID: 0503_user_editor_default
Revises: 0502_backfill_template_cat
Create Date: 2026-01-27 14:32:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0503_add_user_rte_default"
down_revision = "0502_backfill_template_cat"

def upgrade():
    op.add_column("users", sa.Column("default_editor_is_rte", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("users", "default_editor_is_rte")

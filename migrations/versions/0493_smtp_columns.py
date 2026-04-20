"""

Revision ID: 0493_smtp_columns
Revises: 0492_add_service_del_template
Create Date: 2025-11-07 17:08:21.019759

"""
import sqlalchemy as sa
from alembic import op

revision = "0493_smtp_columns"
down_revision = "0492_add_service_del_template"


def upgrade():
    op.add_column("services", sa.Column("smtp_user", sa.Text(), nullable=True))
    op.add_column("services_history", sa.Column("smtp_user", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("services", "smtp_user")
    op.drop_column("services_history", "smtp_user")

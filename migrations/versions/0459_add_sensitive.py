"""
Revision ID: 0459_add_sensitive
Revises: 0458_drop_null_history
Create Date: 2024-06-25 13:32:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0459_add_sensitive"
down_revision = "0458_drop_null_history"


def upgrade():
    op.add_column("services", sa.Column("sensitive_service", sa.Boolean(), nullable=True))
    op.create_index(op.f("ix_service_sensitive_service"), "services", ["sensitive_service"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_service_sensitive_service"), table_name="services")
    op.drop_column("services", "sensitive_service")

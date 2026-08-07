"""

Revision ID: 0522_add_api_key_to_reports
Revises: 0521_update_bounce_rate_warn
Create Date: 2026-07-30

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "0522_add_api_key_to_reports"
down_revision = "0521_update_bounce_rate_warn"


def upgrade():
    inspector = inspect(op.get_bind())

    existing_columns = [column["name"] for column in inspector.get_columns("reports")]
    if "api_key_id" not in existing_columns:
        op.add_column("reports", sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True))

    existing_indexes = [index["name"] for index in inspector.get_indexes("reports")]
    if "ix_reports_api_key_id" not in existing_indexes:
        op.create_index(op.f("ix_reports_api_key_id"), "reports", ["api_key_id"], unique=False)

    existing_fks = [fk["name"] for fk in inspector.get_foreign_keys("reports")]
    if "reports_api_key_id_fkey" not in existing_fks:
        op.create_foreign_key("reports_api_key_id_fkey", "reports", "api_keys", ["api_key_id"], ["id"])


def downgrade():
    op.drop_constraint("reports_api_key_id_fkey", "reports", type_="foreignkey")
    op.drop_index(op.f("ix_reports_api_key_id"), table_name="reports")
    op.drop_column("reports", "api_key_id")

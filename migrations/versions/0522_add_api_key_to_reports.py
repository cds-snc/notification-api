"""

Revision ID: 0522_add_api_key_to_reports
Revises: 0521_update_bounce_rate_warn
Create Date: 2026-07-30

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0522_add_api_key_to_reports"
down_revision = "0521_update_bounce_rate_warn"


def upgrade():
    op.add_column("reports", sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_reports_api_key_id"), "reports", ["api_key_id"], unique=False)
    op.create_foreign_key("reports_api_key_id_fkey", "reports", "api_keys", ["api_key_id"], ["id"])


def downgrade():
    op.drop_constraint("reports_api_key_id_fkey", "reports", type_="foreignkey")
    op.drop_index(op.f("ix_reports_api_key_id"), table_name="reports")
    op.drop_column("reports", "api_key_id")

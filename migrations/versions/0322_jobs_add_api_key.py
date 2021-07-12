"""

Revision ID: 0322_jobs_add_api_key
Revises: 0321_daily_limit_updated
Create Date: 2021-06-07 13:37:42

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0322_jobs_add_api_key"
down_revision = "0321_daily_limit_updated"


def upgrade():
    op.add_column("jobs", sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True)),
    op.create_foreign_key(
        "jobs_api_keys_id_fkey",
        "jobs",
        "api_keys",
        ["api_key_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_jobs_api_key_id"),
        "jobs",
        ["api_key_id"],
        unique=False,
    )


def downgrade():
    op.drop_constraint("jobs_api_keys_id_fkey", "jobs", type_="foreignkey")
    op.drop_index(
        op.f("ix_jobs_api_key_id"),
        table_name="jobs",
    )
    op.drop_column("jobs", "api_key_id")

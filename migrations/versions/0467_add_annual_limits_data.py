"""
Revision ID: 0464_add_annual_limits_data
Revises: 0463_add_annual_limit_column
Create Date: 2024-10-31 13:32:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0464_add_annual_limits_data"
down_revision = "0463_add_annual_limit_column"


def upgrade():
    op.create_table(
        "annual_limits_data",
        sa.Column("service_id", UUID, nullable=False),
        sa.Column("time_period", sa.VARCHAR, nullable=False),
        sa.Column("annual_email_limit", sa.BigInteger, nullable=False),
        sa.Column("annual_sms_limit", sa.BigInteger, nullable=False),
        sa.Column("notification_type", sa.Enum(name="notification_type", native_enum=False, create_type=False), nullable=False),
        sa.Column("notification_count", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], name="fk_service_id"),
    )
    op.create_index("ix_service_id_notification_type", "annual_limits_data", ["service_id", "notification_type"])


def downgrade():
    op.drop_table("annual_limits_data")

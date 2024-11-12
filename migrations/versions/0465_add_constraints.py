"""
Revision ID: 0465_add_constraints
Revises: 0464_add_annual_limits_data
Create Date: 2024-10-31 13:32:00
"""
from alembic import op

revision = "0465_add_constraints"
down_revision = "0464_add_annual_limits_data"


def upgrade():
    op.create_index(
        "ix_service_id_notification_type_time", "annual_limits_data", ["time_period", "service_id", "notification_type"]
    )
    op.create_unique_constraint(
        "uq_service_id_notification_type_time_period", "annual_limits_data", ["service_id", "notification_type", "time_period"]
    )


def downgrade():
    op.drop_constraint("uq_service_id_notification_type_time_period", "annual_limits_data")
    op.drop_index("ix_service_id_notification_type_time", "annual_limits_data")

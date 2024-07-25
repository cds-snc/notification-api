"""

Revision ID: 0422_add_billable_units
Revises: 0421_add_sms_daily_limit
Create Date: 2022-09-082 15:45:00

"""
import sqlalchemy as sa
from alembic import op

revision = "0422_add_billable_units"
down_revision = "0421_add_sms_daily_limit"

user = "postgres"
timeout = 1200  # in seconds, i.e. 20 minutes
default = 1


def upgrade():
    op.add_column(
        "ft_notification_status",
        sa.Column("billable_units", sa.Integer(), nullable=True),
    )
    op.execute(f"UPDATE ft_notification_status SET billable_units = notification_count")
    op.alter_column("ft_notification_status", "billable_units", nullable=False)


def downgrade():
    op.drop_column("ft_notification_status", "billable_units")

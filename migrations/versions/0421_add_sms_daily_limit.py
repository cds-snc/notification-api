"""

Revision ID: 0421_add_sms_daily_limit
Revises: 0420_add_redacted_template
Create Date: 2022-09-02 16:00:00

"""
import sqlalchemy as sa
from alembic import op

revision = "0421_add_sms_daily_limit"
down_revision = "0420_add_redacted_template"

user = "postgres"
timeout = 1200  # in seconds, i.e. 20 minutes
default = 1000


def upgrade():
    op.add_column("services", sa.Column("sms_daily_limit", sa.BigInteger(), nullable=True))
    op.execute(f"UPDATE services SET sms_daily_limit = {default}")
    op.alter_column("services", "sms_daily_limit", nullable=False)

    op.add_column("services_history", sa.Column("sms_daily_limit", sa.BigInteger(), nullable=True))
    op.execute(f"UPDATE services_history SET sms_daily_limit = {default}")
    op.alter_column("services_history", "sms_daily_limit", nullable=False)


def downgrade():
    op.drop_column("services", "sms_daily_limit")
    op.drop_column("services_history", "sms_daily_limit")

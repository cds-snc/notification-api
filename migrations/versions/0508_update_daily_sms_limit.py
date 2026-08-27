"""
Revision ID: 0508_update_daily_sms_limit
Revises: 0507_sms_templates_parts
Create Date: 2026-03-18 00:00:00

Update sms_daily_limit from 1000 to 1500 for all services
that currently have the default limit of 1000.
"""
from alembic import op

revision = "0508_update_daily_sms_limit"
down_revision = "0507_sms_templates_parts"


def upgrade():
    op.execute(
        """
        UPDATE services
        SET sms_daily_limit = 1500
        WHERE sms_daily_limit = 1000
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE services
        SET sms_daily_limit = 1000
        WHERE sms_daily_limit = 1500
        """
    )

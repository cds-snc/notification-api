"""
Revision ID: 0511_update_daily_sms_limit
Revises: 0510_update_free_sms_limit
Create Date: 2026-04-30 00:00:00

Update sms_daily_limit from 1000 to 1500 for all services
that currently have the default limit of 1000.

Services that went live after migration 0508 ran were assigned
1000 again by the admin's DEFAULT_LIVE_SMS_DAILY_LIMIT config
value (which has since been corrected to 1500).
"""
from alembic import op

revision = "0511_update_daily_sms_limit"
down_revision = "0510_update_free_sms_limit"


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

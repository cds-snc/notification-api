"""
Revision ID: 0510_update_free_sms_limit
Revises: 0509_use_custom_unsub_url
Create Date: 2026-04-30 00:00:00

Update free_sms_fragment_limit to 100000 for all annual_billing rows for the
current fiscal year (2026, i.e. April 1, 2026 – March 31, 2027).
"""
from alembic import op

revision = "0510_update_free_sms_limit"
down_revision = "0509_use_custom_unsub_url"


def upgrade():
    op.execute(
        """
        UPDATE annual_billing
        SET free_sms_fragment_limit = 100000
        WHERE financial_year_start = 2026
        """
    )


def downgrade():
    # No-op: previous per-service values varied and are not recoverable.
    pass

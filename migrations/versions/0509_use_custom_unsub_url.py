"""Add use_custom_unsubscribe_url to templates and templates_history.

Revision ID: 0509_use_custom_unsub_url
Revises: 0508_update_daily_sms_limit
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0509_use_custom_unsub_url"
down_revision = "0508_update_daily_sms_limit"


def upgrade():
    op.add_column("templates", sa.Column("use_custom_unsubscribe_url", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "templates_history", sa.Column("use_custom_unsubscribe_url", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade():
    op.drop_column("templates_history", "use_custom_unsubscribe_url")
    op.drop_column("templates", "use_custom_unsubscribe_url")

"""
Revision ID: 0462_add_annual_limit_column
Revises: 0461_add_rtl_column_templates
Create Date: 2024-06-27 13:32:00
"""
import os

from app import config

import sqlalchemy as sa
from alembic import op

revision = "0462_add_annual_limit_column"
down_revision = "0461_add_rtl_column_templates"

cfg = config.configs[os.environ["NOTIFY_ENVIRONMENT"]] # type: ignore
default_email_annual_limit = str(cfg.SERVICE_ANNUAL_EMAIL_LIMIT)
default_sms_annual_limit = str(cfg.SERVICE_ANNUAL_SMS_LIMIT)


def upgrade():
    # Add the new column to the templates table
    op.add_column("services", sa.Column("email_annual_limit", sa.BigInteger(), nullable=True, server_default=default_email_annual_limit))
    op.add_column("services", sa.Column("sms_annual_limit", sa.BigInteger(), nullable=True, server_default=default_sms_annual_limit))
    # Add the new column to the templates_history table
    op.add_column("services_history", sa.Column("email_annual_limit", sa.BigInteger(), nullable=True, server_default=default_email_annual_limit))
    op.add_column("services_history", sa.Column("sms_annual_limit", sa.BigInteger(), nullable=True, server_default=default_sms_annual_limit))

    # Set the default values for existing services
    op.execute(f"""
            UPDATE services
            SET email_annual_limit = {default_email_annual_limit},
            sms_annual_limit = {default_sms_annual_limit}
        """
    )
    # Since sms / email annual limit have been statically set to 25k and 10mil respectively
    # we can update all service history rows safely
    op.execute(f"""
            UPDATE services_history
            SET email_annual_limit = {default_email_annual_limit},
            sms_annual_limit = {default_sms_annual_limit}
        """
    )

    op.alter_column("services", "email_annual_limit", nullable=False)
    op.alter_column("services", "sms_annual_limit", nullable=False)
    op.alter_column("services_history", "email_annual_limit", nullable=False)
    op.alter_column("services_history", "sms_annual_limit", nullable=False)


def downgrade():
    # Remove the column from the services table
    op.drop_column("services", "email_annual_limit")
    op.drop_column("services", "sms_annual_limit")

    # Remove the column from the services_history table
    op.drop_column("services_history", "email_annual_limit")
    op.drop_column("services_history", "sms_annual_limit")

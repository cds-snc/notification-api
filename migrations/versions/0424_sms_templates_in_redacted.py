"""

Revision ID: 0424_sms_templates_in_redacted
Revises: 0423_daily_sms_limit_updated
Create Date: 2022-10-13 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0424_sms_templates_in_redacted"
down_revision = "0423_daily_sms_limit_updated"

near_sms_limit_template_id = current_app.config["NEAR_DAILY_SMS_LIMIT_TEMPLATE_ID"]
at_sms_limit_template_id = current_app.config["REACHED_DAILY_SMS_LIMIT_TEMPLATE_ID"]
daily_sms_limit_updated_id = current_app.config["DAILY_SMS_LIMIT_UPDATED_TEMPLATE_ID"]

template_ids = [near_sms_limit_template_id, at_sms_limit_template_id, daily_sms_limit_updated_id]


def upgrade():
    for template_id in template_ids:
        op.execute(
            """
            INSERT INTO template_redacted
            (
                template_id,
                redact_personalisation,
                updated_at,
                updated_by_id
            ) VALUES ( '{}', false, current_timestamp, '{}' )
            """.format(
                template_id, current_app.config["NOTIFY_USER_ID"]
            )
        )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))

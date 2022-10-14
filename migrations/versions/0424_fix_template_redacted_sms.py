"""

Revision ID: 0424_fix_template_redacted_sms
Revises: 0423_daily_sms_limit_updated
Create Date: 2022-10-14 00:00:00.000000

"""
from alembic import op
from flask import current_app

revision = "0424_fix_template_redacted_sms"
down_revision = "0423_daily_sms_limit_updated"

daily_limit_updated_id = current_app.config["DAILY_SMS_LIMIT_UPDATED_TEMPLATE_ID"]
near_daily_limit_id = current_app.config["NEAR_DAILY_SMS_LIMIT_TEMPLATE_ID"]
reached_daily_limit_id = current_app.config["REACHED_DAILY_SMS_LIMIT_TEMPLATE_ID"]

template_ids = [daily_limit_updated_id, near_daily_limit_id, reached_daily_limit_id]


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

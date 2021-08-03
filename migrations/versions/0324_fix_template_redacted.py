"""

Revision ID: 0324_fix_template_redacted
Revises: 0323_jobs_add_sender_id
Create Date: 2021-07-29 10:20:34.474967

"""
from alembic import op
from flask import current_app

revision = "0324_fix_template_redacted"
down_revision = "0323_jobs_add_sender_id"

daily_limit_updated_id = current_app.config["DAILY_LIMIT_UPDATED_TEMPLATE_ID"]
near_daily_limit_id = current_app.config["NEAR_DAILY_LIMIT_TEMPLATE_ID"]
reached_daily_limit_id = current_app.config["REACHED_DAILY_LIMIT_TEMPLATE_ID"]

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

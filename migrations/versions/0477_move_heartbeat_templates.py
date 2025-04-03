"""
Revision ID: 0477_move_heartbeat_templates
Revises: 0476_add_reports_table
Create Date: 2025-04-02 00:00:00
"""
from datetime import datetime, timezone

from alembic import op
from flask import current_app

revision = "0477_move_heartbeat_templates"
down_revision = "0476_add_reports_table"

TEMPLATE_ID_EMAIL_LOW = current_app.config["HEARTBEAT_TEMPLATE_EMAIL_LOW"]
TEMPLATE_ID_EMAIL_MEDIUM = current_app.config["HEARTBEAT_TEMPLATE_EMAIL_MEDIUM"]
TEMPLATE_ID_EMAIL_HIGH = current_app.config["HEARTBEAT_TEMPLATE_EMAIL_HIGH"]
TEMPLATE_ID_SMS_LOW = current_app.config["HEARTBEAT_TEMPLATE_SMS_LOW"]
TEMPLATE_ID_SMS_MEDIUM = current_app.config["HEARTBEAT_TEMPLATE_SMS_MEDIUM"]
TEMPLATE_ID_SMS_HIGH = current_app.config["HEARTBEAT_TEMPLATE_SMS_HIGH"]

NOTIFY_USER_ID = "6af522d0-2915-4e52-83a3-3690455a5fe6"
NOTIFY_SERVICE_ID = "d6aa2c68-a2d9-4437-ab19-3ae8eb202553"
NOTIFY_HEARTBEAT_SERVICE_ID = "30b2fb9c-f8ad-49ad-818a-ed123fc00758"
CDS_ORGANISATION_ID = "0bf242b4-d37e-4658-bacb-a7ff95bf91cc"

TEMPLATE_IDS = [TEMPLATE_ID_EMAIL_LOW, TEMPLATE_ID_EMAIL_MEDIUM, TEMPLATE_ID_EMAIL_HIGH,
                TEMPLATE_ID_SMS_LOW, TEMPLATE_ID_SMS_MEDIUM, TEMPLATE_ID_SMS_HIGH]

TEMPLATE_UPDATE = """
    UPDATE templates SET service_id = '{}'
    WHERE id = '{}'
"""

TEMPLATE_HISTORY_UPDATE = """
    UPDATE templates_history SET service_id = '{}'
    WHERE id = '{}'
"""

NOW = datetime.now(timezone.utc)

def upgrade():
    heartbeat_service_insert = f"""INSERT INTO services (id, name, created_at, active, count_as_live, message_limit, sms_daily_limit, email_annual_limit, sms_annual_limit, restricted, research_mode, organisation_type, organisation_id, email_from, created_by_id, version)
                        VALUES ('{NOTIFY_HEARTBEAT_SERVICE_ID}', 'GCNotify Heartbeat', '{NOW}', True, False, 20_000, 20_000, 5_000_000, 5_000_000, False, False, 'central', '{CDS_ORGANISATION_ID}', 'gc.notify.heartbeat.notification.gc',
                        '{NOTIFY_USER_ID}', 1)
                    """
    op.execute(heartbeat_service_insert)
    
    heartbeat_service_history_insert = f"""INSERT INTO services_history (id, name, created_at, active, count_as_live, message_limit, sms_daily_limit, email_annual_limit, sms_annual_limit, restricted, research_mode, organisation_type, organisation_id, email_from, created_by_id, version)
                        VALUES ('{NOTIFY_HEARTBEAT_SERVICE_ID}', 'GCNotify Heartbeat', '{NOW}', True, False, 20_000, 20_000, 5_000_000, 5_000_000, False, False, 'central', '{CDS_ORGANISATION_ID}', 'gc.notify.heartbeat.notification.gc',
                        '{NOTIFY_USER_ID}', 1)

                     """
    op.execute(heartbeat_service_history_insert)
    
    user_to_service_insert = """INSERT INTO user_to_service (user_id, service_id) VALUES ('{}', '{}')"""
    op.execute(user_to_service_insert.format(NOTIFY_USER_ID, NOTIFY_HEARTBEAT_SERVICE_ID))

    for template_id in TEMPLATE_IDS:
        op.execute(
            TEMPLATE_UPDATE.format(
                NOTIFY_HEARTBEAT_SERVICE_ID,
                template_id
            )
        )

        op.execute(
            TEMPLATE_HISTORY_UPDATE.format(
                NOTIFY_HEARTBEAT_SERVICE_ID,
                template_id
            )
        )


def downgrade():
    heartbeat_service_delete = f"""DELETE FROM services WHERE id = '{NOTIFY_HEARTBEAT_SERVICE_ID}'"""
    op.execute(heartbeat_service_delete)

    heartbeat_service_history_delete = f"""DELETE FROM services_history WHERE id = '{NOTIFY_HEARTBEAT_SERVICE_ID}'"""
    op.execute(heartbeat_service_history_delete)

    user_to_service_delete = """DELETE FROM user_to_service WHERE user_id = '{}' AND service_id = '{}'"""
    op.execute(user_to_service_delete.format(NOTIFY_USER_ID, NOTIFY_HEARTBEAT_SERVICE_ID))

    for template_id in TEMPLATE_IDS:
        op.execute(
            TEMPLATE_UPDATE.format(
                NOTIFY_SERVICE_ID,
                template_id
            )
        )

        op.execute(
            TEMPLATE_HISTORY_UPDATE.format(
                NOTIFY_SERVICE_ID,
                template_id
            )
        )

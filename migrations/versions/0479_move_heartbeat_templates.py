"""
Revision ID: 0479_move_heartbeat_templates
Revises: 0478_add_report_language
Create Date: 2025-04-02 00:00:00
"""
from datetime import datetime, timezone

from alembic import op
from flask import current_app

revision = "0479_move_heartbeat_templates"
down_revision = "0478_add_report_language"

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
    heartbeat_service_insert = f"""INSERT INTO services (id, name, created_at, active, count_as_live, message_limit, sms_daily_limit, email_annual_limit, sms_annual_limit, restricted, research_mode, prefix_sms, organisation_type, organisation_id, email_from, created_by_id, version)
                        VALUES ('{NOTIFY_HEARTBEAT_SERVICE_ID}', 'GCNotify Heartbeat', '{NOW}', True, False, 20000, 20000, 5000000, 5000000, False, False, False, 'central', '{CDS_ORGANISATION_ID}', 'gc.notify.heartbeat.notification.gc',
                        '{NOTIFY_USER_ID}', 1)
                    """
    op.execute(heartbeat_service_insert)

    heartbeat_service_history_insert = f"""INSERT INTO services_history (id, name, created_at, active, count_as_live, message_limit, sms_daily_limit, email_annual_limit, sms_annual_limit, restricted, research_mode, prefix_sms, organisation_type, organisation_id, email_from, created_by_id, version)
                        VALUES ('{NOTIFY_HEARTBEAT_SERVICE_ID}', 'GCNotify Heartbeat', '{NOW}', True, False, 20000, 20000, 5000000, 5000000, False, False, False, 'central', '{CDS_ORGANISATION_ID}', 'gc.notify.heartbeat.notification.gc',
                        '{NOTIFY_USER_ID}', 1)
                     """
    op.execute(heartbeat_service_history_insert)
    
    for send_type in ('sms', 'email'):
        heartbeat_service_permissions_insert = f"""INSERT INTO service_permissions (service_id, permission, created_at) VALUES ('{NOTIFY_HEARTBEAT_SERVICE_ID}', '{send_type}', '{NOW}')"""
        op.execute(heartbeat_service_permissions_insert)

    # Copy the service permissions from the existing Notify service to the new Heartbeat service.
    perms_insert = f"""
        INSERT INTO permissions (id, service_id, user_id, permission, created_at)
            SELECT uuid_in(md5(random()::text)::cstring), '{NOTIFY_HEARTBEAT_SERVICE_ID}', user_id, permission, '{NOW}'
              FROM permissions
             WHERE service_id = '{NOTIFY_SERVICE_ID}'
    """
    op.execute(perms_insert)

    # The annual billing is required for new services. Let's copy the annual billing
    # data from existing Notify service to the new heartbeat service.
    annual_billing_insert = f"""
        INSERT INTO annual_billing 
        (id, service_id, financial_year_start, free_sms_fragment_limit, created_at, updated_at) 
         SELECT uuid_in(md5(random()::text)::cstring), '{NOTIFY_HEARTBEAT_SERVICE_ID}', financial_year_start, free_sms_fragment_limit, created_at, updated_at 
           FROM annual_billing
          WHERE service_id = '{NOTIFY_SERVICE_ID}'
          ORDER BY financial_year_start DESC
          LIMIT 1
    """
    op.execute(annual_billing_insert)
    
    user_to_service_insert = f"""INSERT INTO user_to_service (user_id, service_id) VALUES ('{NOTIFY_USER_ID}', '{NOTIFY_HEARTBEAT_SERVICE_ID}')"""
    op.execute(user_to_service_insert)

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
    annual_billing_delete = f"""DELETE FROM annual_billing WHERE service_id = '{NOTIFY_HEARTBEAT_SERVICE_ID}'"""
    op.execute(annual_billing_delete)

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

    heartbeat_permissions_delete = f"""DELETE FROM permissions WHERE service_id = '{NOTIFY_HEARTBEAT_SERVICE_ID}'"""
    op.execute(heartbeat_permissions_delete)

    heartbeat_service_permissions_delete = f"""DELETE FROM service_permissions WHERE service_id = '{NOTIFY_HEARTBEAT_SERVICE_ID}'"""
    op.execute(heartbeat_service_permissions_delete)

    heartbeat_service_delete = f"""DELETE FROM services WHERE id = '{NOTIFY_HEARTBEAT_SERVICE_ID}'"""
    op.execute(heartbeat_service_delete)

    heartbeat_service_history_delete = f"""DELETE FROM services_history WHERE id = '{NOTIFY_HEARTBEAT_SERVICE_ID}'"""
    op.execute(heartbeat_service_history_delete)

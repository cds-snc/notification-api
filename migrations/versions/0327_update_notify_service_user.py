"""

Revision ID: e500f72470d0
Revises: 0326_notification_status_reason
Create Date: 2021-04-20 14:25:06.741578

"""
from alembic import op

revision = '0327_update_notify_service_user'
down_revision = '0326_notification_status_reason'


def upgrade():
    op.execute("""
        UPDATE 
            users
        SET 
            email_address = 'vanotify@va.gov'
        WHERE 
            id='6af522d0-2915-4e52-83a3-3690455a5fe6'
    """)


def downgrade():
    op.execute("""
        UPDATE 
            users
        SET 
            email_address = 'va-notify-user@public.govdelivery.com'
        WHERE 
            id='6af522d0-2915-4e52-83a3-3690455a5fe6'
    """)
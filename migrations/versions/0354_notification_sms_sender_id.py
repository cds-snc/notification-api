"""
Revision ID: 0354_notification_sms_sender_id
Revises: 0353_inbound_number_add_fields
Create Date: 2022-12-28 01:28:25.790519
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0354_notification_sms_sender_id'
down_revision = '0353_inbound_number_add_fields'


def upgrade():
    op.add_column('notifications', sa.Column('sms_sender_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('notifications_to_service_sms_senders', 'notifications', 'service_sms_senders', ['sms_sender_id'], ['id'])

    op.add_column('notification_history', sa.Column('sms_sender_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('notification_history_to_service_sms_senders', 'notification_history', 'service_sms_senders', ['sms_sender_id'], ['id'])

    # The "notifications" table already has this relation.  I added it to notification_history for consistency.
    op.create_foreign_key('notification_history_to_users', 'notification_history', 'users', ['created_by_id'], ['id'])


def downgrade():
    op.drop_constraint('notifications_to_service_sms_senders', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'sms_sender_id')

    op.drop_constraint('notification_history_to_service_sms_senders', 'notification_history', type_='foreignkey')
    op.drop_constraint('notification_history_to_users', 'notification_history', type_='foreignkey')
    op.drop_column('notification_history', 'sms_sender_id')

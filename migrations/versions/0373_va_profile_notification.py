"""
Revision ID: 0373_va_profile_notification
Revises: 0372_remove_service_id_index
Create Date: 2024-10-22 12:56:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0373_va_profile_notification'
down_revision = '0372_remove_service_id_index'

def upgrade():
    op.add_column('va_profile_local_cache', sa.Column('notification_id', UUID(), nullable=True))

def downgrade():
    op.drop_column('va_profile_local_cache', 'notification_id')
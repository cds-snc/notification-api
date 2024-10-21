"""

Revision ID: 0372_remove_service_id_index
Revises: 0371_replace_template_content
Create Date: 2024-10-21 17:22:11.386188

"""
from alembic import op

revision = '0372_remove_service_id_index'
down_revision = '0371_replace_template_content'


def upgrade():
    op.drop_index(op.f('ix_notifications_service_id'), table_name='notifications')


def downgrade():
    op.create_index(op.f('ix_notifications_service_id'), 'notifications', ['service_id'], unique=False)

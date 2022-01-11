"""

Revision ID: 0339_add_push_notif_permission
Revises: 0338_update_fact_notif_status
Create Date: 2021-12-20 12:51:00.553275

"""
from alembic import op
from app.models.models import PUSH_TYPE


revision = '0339_add_push_notif_permission'
down_revision = '0338_update_fact_notif_status'


def upgrade():
    op.execute(f"INSERT INTO service_permission_types VALUES ('{PUSH_TYPE}')")


def downgrade():
    op.execute(f"DELETE FROM service_permissions WHERE permission = '{PUSH_TYPE}'")
    op.execute(f"DELETE FROM service_permission_types WHERE name = '{PUSH_TYPE}'")

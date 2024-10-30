"""

Revision ID: 0339_add_push_notif_permission
Revises: 0338a_fact_notif_pkey_constraint
Create Date: 2021-12-20 12:51:00.553275

"""
from alembic import op

from app.constants import PUSH_TYPE


revision = '0339_add_push_notif_permission'
down_revision = '0338a_fact_notif_pkey_constraint'


def upgrade():
    op.execute(f"INSERT INTO service_permission_types VALUES ('{PUSH_TYPE}')")  # nosec


def downgrade():
    op.execute(f"DELETE FROM service_permissions WHERE permission = '{PUSH_TYPE}'")  # nosec
    op.execute(f"DELETE FROM service_permission_types WHERE name = '{PUSH_TYPE}'")  # nosec

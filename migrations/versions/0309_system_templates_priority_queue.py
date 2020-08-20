"""

Revision ID: 0309_system_templates_priority
Revises: 0308_rename_service_whitelist
Create Date: 2020-08-04 12:50:00

"""
from alembic import op


revision = '0309_system_templates_priority'
down_revision = '0308_rename_service_whitelist'


def upgrade():
    op.execute("UPDATE templates SET process_type = 'priority' WHERE service_id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'")

def downgrade():
    op.execute("UPDATE templates SET process_type = 'normal' WHERE service_id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'")

"""

Revision ID: 0330a_grant_edit_templates
Revises: 0330_edit_templates_permission
Create Date: 2021-06-25 12:09:50.892373

"""
import uuid
from datetime import datetime
from alembic import op

revision = '0330a_grant_edit_templates'
down_revision = '0330_edit_templates_permission'


def upgrade():
    conn = op.get_bind()
    results = conn.execute("SELECT service_id, user_id FROM permissions WHERE permission = 'manage_templates'")
    users_with_manage_templates_permission = results.fetchall()

    for user_permission in users_with_manage_templates_permission:
        conn.execute(f"""
            INSERT INTO permissions (id, service_id, user_id, permission, created_at) 
            VALUES ('{uuid.uuid4()}', '{user_permission.service_id}', '{user_permission.user_id}', 'edit_templates', '{datetime.utcnow()}')
        """)


def downgrade():
    op.execute("DELETE FROM permissions WHERE permission = 'edit_templates'")

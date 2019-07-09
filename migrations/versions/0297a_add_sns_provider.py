"""

Revision ID: 0297a_add_sns_provider
Revises: 0297_template_redacted_fix
Create Date: 2019-07-09 08:49:20.630174

"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = '0297a_add_sns_provider'
down_revision = '0297_template_redacted_fix'


def upgrade():
    op.execute(f"""
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{uuid.uuid4()}', 'AWS SNS', 'sns', 0, 'sms', true, 1)
    """)


def downgrade():
    op.execute("DELETE FROM provider_details WHERE name = 'sns'")
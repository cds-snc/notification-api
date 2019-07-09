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

id = uuid.uuid4()


def upgrade():
    op.execute(f"""
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'AWS SNS', 'sns', 10, 'sms', true, 1)
    """)
    op.execute(f"""
        INSERT INTO provider_details_history (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'AWS SNS', 'sns', 10, 'sms', true, 1)
    """)
    op.execute("UPDATE provider_details SET priority = 15 where identifier='mmg'")


def downgrade():
    op.execute("DELETE FROM provider_details WHERE identifier = 'sns'")
    op.execute("DELETE FROM provider_details_history WHERE identifier = 'sns'")
    op.execute("UPDATE provider_details SET priority = 10 where identifier='mmg'")
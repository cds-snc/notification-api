"""

Revision ID: 0305m_add_pinpoint
Revises: 0305l_smtp_template
Create Date: 2020-04-20 12:00:00

"""
from alembic import op
import sqlalchemy as sa
import uuid


revision = '0305m_add_pinpoint'
down_revision = '0305l_smtp_template'

id = uuid.uuid4()


def upgrade():
    op.execute(f"""
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'AWS Pinpoint', 'pinpoint', 12, 'sms', true, 1)
    """)
    op.execute(f"""
        INSERT INTO provider_details_history (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'AWS Pinpoint', 'pinpoint', 12, 'sms', true, 1)
    """)
    op.execute("UPDATE provider_details SET priority = 15 where identifier='mmg'")


def downgrade():
    op.execute("DELETE FROM provider_details WHERE identifier = 'pinpoint'")
    op.execute("DELETE FROM provider_details_history WHERE identifier = 'pinpoint'")
    op.execute("UPDATE provider_details SET priority = 12 where identifier='mmg'")
"""

Revision ID: 0306_add_twilio_provider
Revises: 0305l_smtp_template
Create Date: 2020-04-22 11:59:20.630174

"""
from alembic import op
import uuid

revision = '0306_add_twilio_provider'
down_revision = '0305l_smtp_template'

id = uuid.uuid4()


def upgrade():
    op.execute(f"""
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'Twilio', 'twilio', 25, 'sms', true, 1)
    """)
    op.execute(f"""
        INSERT INTO provider_details_history (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'Twilio', 'twilio', 25, 'sms', true, 1)
    """)


def downgrade():
    op.execute("DELETE FROM provider_details WHERE identifier = 'twilio'")
    op.execute("DELETE FROM provider_details_history WHERE identifier = 'twilio'")

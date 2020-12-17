"""

Revision ID: 0314_add_pinpoint_provider
Revises: 0313_add_birls_identifier_type
Create Date: 2020-12-15 16:02:56.906384

"""
from alembic import op
import uuid

id = uuid.uuid4()

revision = '0314_add_pinpoint_provider'
down_revision = '0313_add_birls_identifier_type'


def upgrade():
    op.execute(f"""
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version)
        VALUES ('{id}', 'AWS Pinpoint', 'pinpoint', 20, 'sms', 'false', 1)
    """)
    op.execute(f"""
        INSERT INTO provider_details_history (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'AWS Pinpoint', 'pinpoint', 20, 'sms', false, 1)
    """)


def downgrade():
   op.execute("DELETE FROM provider_details WHERE identifier = 'pinpoint'")
   op.execute("DELETE FROM provider_details_history WHERE identifier = 'pinpoint'")

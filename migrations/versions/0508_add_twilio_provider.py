"""
Revision ID: 0508_add_twilio_provider
Revises: 0507_add_rcs_notification_type
Create Date: 2026-03-05 00:00:00

Add Twilio as a provider option in the provider_details table.
"""
from alembic import op
import uuid

revision = "0508_add_twilio_provider"
down_revision = "0507_add_rcs_notification_type"


def upgrade():
    # Add Twilio as a provider option in the provider_details table
    op.execute(
        """
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version)
        SELECT '{}'::uuid, 'Twilio', 'twilio', 10, 'rcs', true, 1
        WHERE NOT EXISTS (
            SELECT 1 FROM provider_details WHERE identifier = 'twilio'
        )
        """.format(str(uuid.uuid4()))
    )


def downgrade():
    # Remove the Twilio provider option from the provider_details table
    op.execute("DELETE FROM provider_details WHERE identifier = 'twilio' AND notification_type = 'rcs'")

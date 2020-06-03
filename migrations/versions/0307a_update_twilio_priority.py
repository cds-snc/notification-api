"""

Revision ID: 0307a_update_twilio_priority
Revises: 0307_add_govdelivery_provider
Create Date: 2020-06-03 08:49:20.630174

"""
from alembic import op
import uuid

revision = '0307a_update_twilio_priority'
down_revision = '0307_add_govdelivery_provider'

id = uuid.uuid4()


def upgrade():
    op.execute("UPDATE provider_details SET priority = 5 where identifier='twilio'")


def downgrade():
    op.execute("UPDATE provider_details SET priority = 25 where identifier='twilio'")

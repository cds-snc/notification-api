"""

Revision ID: 0307b_deactivate_mmg_loadtesting
Revises: 0307a_update_twilio_priority
Create Date: 2020-06-03 08:49:20.630174

"""
from alembic import op
import uuid

revision = '0307b_deactivate_mmg_loadtesting'
down_revision = '0307a_update_twilio_priority'

id = uuid.uuid4()


def upgrade():
    op.execute("UPDATE provider_details SET active = false where identifier='mmg'")
    op.execute("UPDATE provider_details SET active = false where identifier='loadtesting'")


def downgrade():
    op.execute("UPDATE provider_details SET active = true where identifier='mmg'")
    op.execute("UPDATE provider_details SET active = true where identifier='loadtesting'")

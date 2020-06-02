"""

Revision ID: 0307_add_govdelivery_provider
Revises: 0306a_increase_number_length
Create Date: 2020-05-28 11:59:20.630174

"""
from alembic import op
import uuid

revision = '0307_add_govdelivery_provider'
down_revision = '0306a_increase_number_length'

id = uuid.uuid4()


def upgrade():
    op.execute(f"""
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'Govdelivery', 'govdelivery', 5, 'email', true, 1)
    """)
    op.execute(f"""
        INSERT INTO provider_details_history (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'Govdelivery', 'govdelivery', 5, 'email', true, 1)
    """)


def downgrade():
    op.execute("DELETE FROM provider_details WHERE identifier = 'govdelivery'")
    op.execute("DELETE FROM provider_details_history WHERE identifier = 'govdelivery'")

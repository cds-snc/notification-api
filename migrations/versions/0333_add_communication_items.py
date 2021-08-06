"""

Revision ID: 0333_add_communication_items
Create Date:

"""
import uuid

revision = '0333_add_communication_items'
down_revision = '0332b_callback_channel_not_null'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade():
    communication_items_table = op.create_table(
        'communication_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('va_profile_item_id', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.bulk_insert(
        communication_items_table,
        [
            {
                'id': uuid.uuid4(),
                'name': name,
                'va_profile_item_id': va_profile_item_id
            }
            for name, va_profile_item_id in
            [
                ["Board of Veterans' Appeals hearing reminder", 1],
                ["COVID-19 Updates", 2],
                ["Appointment reminders", 3],
                ["Prescription shipment and tracking updates", 4]
            ]
        ]
    )


def downgrade():
    op.drop_table('communication_items')

"""

Revision ID: 0312_recipient_identifiers_table
Revises: 0311_make_to_field_nullable
Create Date: 2020-10-12 09:09:09.093272

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0312_recipient_identifiers_table'
down_revision = '0311_make_to_field_nullable'


def upgrade():
    op.create_table(
        'recipient_identifiers',
        sa.Column('notification_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('va_identifier_type', sa.Enum('VAPROFILEID', 'PID', 'ICN', name='va_identifier_types'),
                  nullable=False),
        sa.Column('va_identifier_value', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('notification_id', 'va_identifier_type', 'va_identifier_value')
    )


def downgrade():
    op.execute('DROP TABLE recipient_identifiers')
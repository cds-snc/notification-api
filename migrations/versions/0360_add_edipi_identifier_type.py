"""

Revision ID: 0360_add_edipi_identifier_type
Revises: 0359_communication_items_unique
Create Date: 2023-07-31 14:48:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0360_add_edipi_identifier_type'
down_revision = '0359_communication_items_unique'

old_id_types = sa.Enum('VAPROFILEID', 'PID', 'ICN', 'BIRLSID', name='id_types')
new_id_types = sa.Enum('VAPROFILEID', 'PID', 'ICN', 'BIRLSID', 'EDIPI', name='id_types')


def upgrade():
    op.execute('ALTER TYPE id_types RENAME to tmp_id_types')
    new_id_types.create(op.get_bind())
    op.execute('ALTER TABLE recipient_identifiers ALTER COLUMN id_type TYPE id_types USING id_type::text::id_types')
    op.execute('DROP TYPE tmp_id_types')


def downgrade():
    op.execute('ALTER TYPE id_types RENAME TO tmp_id_types')
    old_id_types.create(op.get_bind())
    op.execute('ALTER TABLE recipient_identifiers ALTER COLUMN id_type TYPE id_types USING id_type::text::id_types')
    op.execute('DROP TYPE tmp_id_types')

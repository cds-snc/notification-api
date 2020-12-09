"""

Revision ID: 0313_add_birls_identifier_type
Revises: 0312_recipient_identifiers_table
Create Date: 2020-12-08 09:09:09.093272

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0313_add_birls_identifier_type'
down_revision = '0312_recipient_identifiers_table'

old_id_types = sa.Enum('VAPROFILEID', 'PID', 'ICN', name='id_types')
new_id_types = sa.Enum('VAPROFILEID', 'PID', 'ICN', 'BIRLSID', name='id_types')


def upgrade():
    op.execute('ALTER TYPE id_types RENAME to tmp_id_types')
    new_id_types.create(op.get_bind())
    op.execute('ALTER TABLE recipient_identifiers ALTER COLUMN id_type TYPE id_types USING id_type::text::id_types')
    op.execute('DROP TYPE tmp_id_types')


def downgrade():

    op.execute('ALTER TYPE id_types RENAME to tmp_id_types')
    old_id_types.create(op.get_bind())
    op.execute('ALTER TABLE recipient_identifiers ALTER COLUMN id_type TYPE id_types USING id_type::text::id_types')
    op.execute('DROP TYPE tmp_id_types')

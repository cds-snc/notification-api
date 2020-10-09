"""

Revision ID: 0311_make_to_field_nullable
Revises: 0310a_make_email_from_nullable
Create Date: 2020-10-09 09:42:09.093272

"""
from alembic import op

revision = '0311_make_to_field_nullable'
down_revision = '0310a_make_email_from_nullable'


def upgrade():
    op.alter_column('notifications', 'to', nullable=True)


def downgrade():
    op.alter_column('notifications', 'to', nullable=False)

"""

Revision ID: 0310a_make_email_from_nullable
Revises: 0310_remove_email_from_unique
Create Date: 2020-08-14 12:02:09.093272

"""
from alembic import op

revision = '0310a_make_email_from_nullable'
down_revision = '0310_remove_email_from_unique'


def upgrade():
    op.alter_column('services', 'email_from', nullable=True)
    op.alter_column('services_history', 'email_from', nullable=True)


def downgrade():
    op.alter_column('services', 'email_from', nullable=False)
    op.alter_column('services_history', 'email_from', nullable=False)

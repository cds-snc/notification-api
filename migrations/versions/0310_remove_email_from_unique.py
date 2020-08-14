"""

Revision ID: 0310_remove_email_from_unique
Revises: 0309_remove_org_type_values
Create Date: 2020-08-14 12:02:09.093272

"""
from alembic import op

revision = '0310_remove_email_from_unique'
down_revision = '0309_remove_org_type_values'


def upgrade():
    op.drop_constraint('services_email_from_key', 'services')

def downgrade():
    op.create_unique_constraint('services_email_from_key', 'services', ['email_from'])

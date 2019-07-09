"""

Revision ID: 0297c_change_primary_user
Revises: 0297b_change_primary_service
Create Date: 2019-07-09 13:22:46.993577

"""
from alembic import op
import sqlalchemy as sa


revision = '0297c_change_primary_user'
down_revision = '0297b_change_primary_service'


def upgrade():
    op.execute("UPDATE users SET email_address = 'notify-service-user@notification.alpha.canada.ca', mobile_number = '+16135555555' where id='6af522d0-2915-4e52-83a3-3690455a5fe6'")


def downgrade():
    op.execute("UPDATE users SET email_address = 'notify-service-user@digital.cabinet-office.gov.uk', mobile_number = '+441234123412' where id='6af522d0-2915-4e52-83a3-3690455a5fe6'")


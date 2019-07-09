"""

Revision ID: 0297b_change_primary_service
Revises: 0297a_add_sns_provider
Create Date: 2019-07-09 13:01:46.993577

"""
from alembic import op
import sqlalchemy as sa


revision = '0297b_change_primary_service'
down_revision = '0297a_add_sns_provider'


def upgrade():
    op.execute("UPDATE services SET name = 'Notification', email_from = 'notification' where id='d6aa2c68-a2d9-4437-ab19-3ae8eb202553'")


def downgrade():
    op.execute("UPDATE services SET name = 'GOV.UK Notify', email_from = 'gov.uk.notify' where id='d6aa2c68-a2d9-4437-ab19-3ae8eb202553'")


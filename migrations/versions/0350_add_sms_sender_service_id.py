"""

Revision ID: 0350_add_sms_sender_service_id
Revises: 0349_delete_old_opt_out_function
Create Date: 2022-07-20 15:43:55.837466

"""
from alembic import op
import sqlalchemy as sa

revision = '0350_add_sms_sender_service_id'
down_revision = '0349_delete_old_opt_out_function'


def upgrade():
    op.add_column('service_sms_senders', sa.Column('sms_sender_specifics', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('service_sms_senders', 'sms_sender_specifics')

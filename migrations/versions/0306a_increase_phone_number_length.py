"""

Revision ID: 0306a_increase_phone_number_length
Revises: 0306_add_twilio_provider
Create Date: 2020-04-27 11:59:20.630174

"""
from alembic import op
import sqlalchemy as sa


revision = '0306a_increase_number_length'
down_revision = '0306_add_twilio_provider'


def upgrade():
    op.alter_column('inbound_numbers', 'number',
                    existing_type=sa.VARCHAR(length=11),
                    type_=sa.String(length=12),
                    existing_nullable=False,
                    existing_server_default=sa.text(u"''::character varying"))
    op.alter_column('service_sms_senders', 'sms_sender',
                    existing_type=sa.VARCHAR(length=11),
                    type_=sa.String(length=12),
                    existing_nullable=False,
                    existing_server_default=sa.text(u"''::character varying"))


def downgrade():
    op.alter_column('inbound_numbers', 'number',
                    existing_type=sa.VARCHAR(length=12),
                    type_=sa.String(length=11),
                    existing_nullable=False,
                    existing_server_default=sa.text(u"''::character varying"))
    op.alter_column('service_sms_senders', 'sms_sender',
                    existing_type=sa.VARCHAR(length=12),
                    type_=sa.String(length=11),
                    existing_nullable=False,
                    existing_server_default=sa.text(u"''::character varying"))

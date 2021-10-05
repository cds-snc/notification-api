"""

Revision ID: 0337a_rate_limit_interval
Revises: 0337_rate_limit_sms_sender_units
Create Date: 2021-10-05 13:56:36.986015

"""
from alembic import op
import sqlalchemy as sa

revision = '0337a_rate_limit_interval'
down_revision = '0337_rate_limit_sms_sender_units'


def upgrade():
    op.drop_constraint('ck_rate_limit_requires_unit_and_value', 'service_sms_senders')
    op.drop_column('service_sms_senders', 'rate_limit_unit')
    op.execute('DROP TYPE rate_limit_unit')
    op.add_column('service_sms_senders', sa.Column('rate_limit_interval', sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_rate_limit_requires_value_and_interval",
        "service_sms_senders",
        "NOT((rate_limit_interval IS NOT NULL AND rate_limit IS NULL) OR"
        "(rate_limit IS NOT NULL AND rate_limit_interval IS NULL))"
    )


def downgrade():
    op.drop_constraint('ck_rate_limit_requires_value_and_interval', 'service_sms_senders')
    op.drop_column('service_sms_senders', 'rate_limit_interval')
    rate_limit_unit = sa.Enum('PER_SECOND', 'PER_MINUTE', name='rate_limit_unit')
    rate_limit_unit.create(op.get_bind())
    op.add_column('service_sms_senders', sa.Column('rate_limit_unit', rate_limit_unit, nullable=True))
    op.execute("UPDATE service_sms_senders SET rate_limit_unit = 'PER_MINUTE' "
               "WHERE rate_limit_unit IS NULL AND rate_limit IS NOT NULL")
    op.create_check_constraint(
        "ck_rate_limit_requires_unit_and_value",
        "service_sms_senders",
        "NOT((rate_limit_unit IS NOT NULL AND rate_limit IS NULL) OR"
        "(rate_limit IS NOT NULL AND rate_limit_unit IS NULL))"
    )


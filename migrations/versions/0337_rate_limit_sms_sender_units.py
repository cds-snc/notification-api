"""

Revision ID: 0337_rate_limit_sms_senderunits
Revises: 0336_add_rate_limit_sms_sender
Create Date: 2021-10-04 12:24:10.628882

"""
from alembic import op
import sqlalchemy as sa

revision = '0337_rate_limit_sms_sender_units'
down_revision = '0336_add_rate_limit_sms_sender'


def upgrade():
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


def downgrade():
    op.drop_column('service_sms_senders', 'rate_limit_unit')
    op.execute('DROP TYPE rate_limit_unit')






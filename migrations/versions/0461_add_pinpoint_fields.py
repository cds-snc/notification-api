"""

Revision ID: 0461_add_pinpoint_fields
Revises: 0460_new_service_columns
Create Date: 2024-10-15 18:24:22.926597

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0461_add_pinpoint_fields'
down_revision = '0460_new_service_columns'


def upgrade():
    op.add_column("notifications", sa.Column("sms_totalMessagePrice", sa.Float(), nullable=True))
    op.add_column("notifications", sa.Column("sms_totalCarrierFee", sa.Float(), nullable=True))
    op.add_column("notifications", sa.Column("sms_isoCountryCode", sa.VARCHAR(), nullable=True))
    op.add_column("notifications", sa.Column("sms_carrierName", sa.VARCHAR(), nullable=True))
    op.add_column("notifications", sa.Column("sms_messageEncoding", sa.VARCHAR(), nullable=True))
    op.add_column("notifications", sa.Column("sms_originationPhoneNumber", sa.VARCHAR(), nullable=True))
    op.add_column("notification_history", sa.Column("sms_totalMessagePrice", sa.Float(), nullable=True))
    op.add_column("notification_history", sa.Column("sms_totalCarrierFee", sa.Float(), nullable=True))
    op.add_column("notification_history", sa.Column("sms_isoCountryCode", sa.VARCHAR(), nullable=True))
    op.add_column("notification_history", sa.Column("sms_carrierName", sa.VARCHAR(), nullable=True))
    op.add_column("notification_history", sa.Column("sms_messageEncoding", sa.VARCHAR(), nullable=True))
    op.add_column("notification_history", sa.Column("sms_originationPhoneNumber", sa.VARCHAR(), nullable=True))
    

def downgrade():
    op.drop_column("notifications", "sms_totalMessagePrice")
    op.drop_column("notifications", "sms_totalCarrierFee")
    op.drop_column("notifications", "sms_isoCountryCode")
    op.drop_column("notifications", "sms_carrierName")
    op.drop_column("notifications", "sms_messageEncoding")
    op.drop_column("notifications", "sms_originationPhoneNumber")
    op.drop_column("notification_history", "sms_totalMessagePrice")
    op.drop_column("notification_history", "sms_totalCarrierFee")
    op.drop_column("notification_history", "sms_isoCountryCode")
    op.drop_column("notification_history", "sms_carrierName")
    op.drop_column("notification_history", "sms_messageEncoding")
    op.drop_column("notification_history", "sms_originationPhoneNumber")

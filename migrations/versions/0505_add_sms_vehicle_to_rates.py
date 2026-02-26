"""
Revision ID: 0505_add_sms_vehicle_to_rates
Revises: 0504_fix_template_link
Create Date: 2026-02-25 00:00:00

Add sms_sending_vehicle column to the rates table so rates can be different
for short code vs long code sends.
"""
import sqlalchemy as sa
from alembic import op

revision = "0505_add_sms_vehicle"
down_revision = "0504_fix_template_link"

# Reference the existing enum type created by 0456_update_template_categories
sms_sending_vehicle = sa.Enum("short_code", "long_code", name="sms_sending_vehicle", create_type=False)


def upgrade():
    op.add_column(
        "rates",
        sa.Column(
            "sms_sending_vehicle",
            sms_sending_vehicle,
            nullable=False,
            server_default="long_code",
        ),
    )


def downgrade():
    op.drop_column("rates", "sms_sending_vehicle")

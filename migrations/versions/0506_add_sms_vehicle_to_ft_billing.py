"""
Revision ID: 0506_add_sms_vehicle_to_ft_billing
Revises: 0505_add_sms_vehicle_to_rates
Create Date: 2026-02-25 00:00:00

Add sms_sending_vehicle to ft_billing as part of the composite primary key.
Different vehicles (short code vs long code) can have different rates and
should be tracked as separate billing rows.
"""
import sqlalchemy as sa
from alembic import op

revision = "0506_add_sms_vehicle_ftb"
down_revision = "0505_add_sms_vehicle"

# Reference the existing enum type created by 0456_update_template_categories
sms_sending_vehicle = sa.Enum("short_code", "long_code", name="sms_sending_vehicle", create_type=False)

FT_BILLING_PK_COLUMNS = [
    "bst_date",
    "template_id",
    "service_id",
    "notification_type",
    "provider",
    "rate_multiplier",
    "international",
    "rate",
    "postage",
    "sms_sending_vehicle",
]


def upgrade():
    # Add the new column with a default so existing rows get a value
    op.add_column(
        "ft_billing",
        sa.Column(
            "sms_sending_vehicle",
            sms_sending_vehicle,
            nullable=False,
            server_default="long_code",
        ),
    )

    # Replace the existing primary key with one that includes sms_sending_vehicle
    op.drop_constraint("ft_billing_pkey", "ft_billing", type_="primary")
    op.create_primary_key("ft_billing_pkey", "ft_billing", FT_BILLING_PK_COLUMNS)


def downgrade():
    op.drop_constraint("ft_billing_pkey", "ft_billing", type_="primary")
    op.create_primary_key(
        "ft_billing_pkey",
        "ft_billing",
        [c for c in FT_BILLING_PK_COLUMNS if c != "sms_sending_vehicle"],
    )
    op.drop_column("ft_billing", "sms_sending_vehicle")

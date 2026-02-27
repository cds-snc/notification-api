"""
Revision ID: 0506_update_ft_billing
Revises: 0505_add_sms_vehicle
Create Date: 2026-02-25 00:00:00

Update `ft_billing` to include `sms_sending_vehicle` in the composite
primary key and add `billing_total` column to store the total cost for
each billing row.
"""
import sqlalchemy as sa
from alembic import op
import uuid

revision = "0506_update_ft_billing"
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

    # Add billing_total column to store the total cost for the row
    op.add_column(
        "ft_billing",
        sa.Column(
            "billing_total",
            sa.Numeric(16, 8),
            nullable=True,
        ),
    )

    # Replace the existing primary key with one that includes sms_sending_vehicle
    op.drop_constraint("ft_billing_pkey", "ft_billing", type_="primary")
    op.create_primary_key("ft_billing_pkey", "ft_billing", FT_BILLING_PK_COLUMNS)

    # Remove any existing rates and insert the new billing rates for SMS
    # valid_from set to 2026-02-27
    op.execute("DELETE FROM rates;")
    op.execute(
        f"""
        INSERT INTO rates (id, valid_from, rate, notification_type, sms_sending_vehicle)
        VALUES
        ('{uuid.uuid4()}', '2026-02-27 00:00:00', 0.02065, 'sms', 'long_code'),
        ('{uuid.uuid4()}', '2026-02-27 00:00:00', 0.06240, 'sms', 'short_code');
        """
    )


def downgrade():
    op.drop_constraint("ft_billing_pkey", "ft_billing", type_="primary")
    op.create_primary_key(
        "ft_billing_pkey",
        "ft_billing",
        [c for c in FT_BILLING_PK_COLUMNS if c != "sms_sending_vehicle"],
    )
    op.drop_column("ft_billing", "sms_sending_vehicle")
    op.drop_column("ft_billing", "billing_total")

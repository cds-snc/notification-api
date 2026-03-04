"""
Revision ID: 0505_add_sms_vehicle
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

    # All existing SMS rates now have sms_sending_vehicle='long_code' (the server default).
    # Insert a short_code mirror for each one so that ft_billing can be regenerated for
    # any historical date in any environment, regardless of when rates were originally inserted.
    op.execute(
        """
        INSERT INTO rates (id, valid_from, rate, notification_type, sms_sending_vehicle)
        SELECT
            gen_random_uuid(),
            lc.valid_from,
            lc.rate,
            'sms',
            'short_code'
        FROM rates lc
        WHERE lc.notification_type = 'sms'
          AND lc.sms_sending_vehicle = 'long_code'
          AND NOT EXISTS (
              SELECT 1
              FROM rates sc
              WHERE sc.notification_type = 'sms'
                AND sc.sms_sending_vehicle = 'short_code'
                AND sc.valid_from = lc.valid_from
          );
        """
    )


def downgrade():
    # Remove short_code mirror rates that were inserted to match existing long_code
    # rates (same valid_from and same rate value).
    op.execute(
        """
        DELETE FROM rates sc
        USING rates lc
        WHERE sc.notification_type = 'sms'
          AND sc.sms_sending_vehicle = 'short_code'
          AND lc.notification_type = 'sms'
          AND lc.sms_sending_vehicle = 'long_code'
          AND sc.valid_from = lc.valid_from
          AND sc.rate = lc.rate;
        """
    )

    op.drop_column("rates", "sms_sending_vehicle")

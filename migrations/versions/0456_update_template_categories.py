"""
Revision ID: 0456_update_template_categories
Revises: 0455_add_starter_category
Create Date: 2024-06-11 13:32:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0456_update_template_categories"
down_revision = "0455_add_starter_category"

LOW_CATEGORY_ID = "0dda24c2-982a-4f44-9749-0e38b2607e89"
MEDIUM_CATEGORY_ID = "f75d6706-21b7-437e-b93a-2c0ab771e28e"
HIGH_CATEGORY_ID = "c4f87d7c-a55b-4c0f-91fe-e56c65bb1871"
CAT_ALERT_ID = "1d8ce435-a7e5-431b-aaa2-a418bc4d14f9"
CAT_AUTH_ID = "b6c42a7e-2a26-4a07-802b-123a5c3198a9"
CAT_AUTO_ID = "977e2a00-f957-4ff0-92f2-ca3286b24786"
CAT_DECISION_ID = "e81678c0-4897-4111-b9d0-172f6b595f89"
CAT_INFO_ID = "207b293c-2ae5-48e8-836d-fcabd60b2153"
CAT_REMINDER_ID = "edb966f3-4a4c-47a4-96ab-05ff259b919c"
CAT_REQUEST_ID = "e0b8fbe5-f435-4977-8fc8-03f13d9296a5"
CAT_STATUS_ID = "55eb1137-6dc6-4094-9031-f61124a279dc"
CAT_TEST_ID = "7c16aa95-e2e1-4497-81d6-04c656520fe4"

SHORT_CODE_CATS = (HIGH_CATEGORY_ID, CAT_AUTH_ID, CAT_AUTO_ID, CAT_DECISION_ID, CAT_REMINDER_ID, CAT_REQUEST_ID, CAT_STATUS_ID)
LONG_CODE_CATS = (LOW_CATEGORY_ID, MEDIUM_CATEGORY_ID, CAT_ALERT_ID, CAT_INFO_ID, CAT_TEST_ID)

sms_options = ("short_code", "long_code")
sms_sending_vehicle = sa.Enum(*sms_options, name="sms_sending_vehicle")


def upgrade():
    sms_sending_vehicle.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "template_categories", sa.Column("sms_sending_vehicle", sms_sending_vehicle, server_default="long_code", nullable=False)
    )

    # Update the generic categories
    op.execute(
        "UPDATE template_categories SET sms_process_type = 'bulk', email_process_type = 'bulk' WHERE id = '{}'".format(
            LOW_CATEGORY_ID,
        )
    )
    op.execute(
        "UPDATE template_categories SET sms_process_type = 'normal', email_process_type = 'normal' WHERE id = '{}'".format(
            MEDIUM_CATEGORY_ID,
        )
    )
    op.execute(
        "UPDATE template_categories SET sms_process_type = 'priority', email_process_type = 'priority' WHERE id = '{}'".format(
            HIGH_CATEGORY_ID,
        )
    )

    # Update the sms_sending_vehicle for the starter categories

    op.execute(
        "UPDATE template_categories SET sms_sending_vehicle = 'short_code' WHERE id in {}".format(
            SHORT_CODE_CATS,
        )
    )

    op.execute(
        "UPDATE template_categories SET sms_sending_vehicle = 'long_code' WHERE id in {}".format(
            LONG_CODE_CATS,
        )
    )


def downgrade():
    op.drop_column("template_categories", "sms_sending_vehicle")
    sms_sending_vehicle.drop(op.get_bind(), checkfirst=True)

"""
Revision ID: 0457_update_categories
Revises: 0456_update_template_categories
Create Date: 2024-06-25 13:32:00
"""
from alembic import op

revision = "0457_update_categories"
down_revision = "0456_update_template_categories"

CAT_ALERT_ID = "1d8ce435-a7e5-431b-aaa2-a418bc4d14f9"


def upgrade():
    op.execute(
        "UPDATE template_categories SET email_process_type='normal', sms_process_type='normal' WHERE id = '{}'".format(
            CAT_ALERT_ID,
        )
    )


def downgrade():
    pass

"""
Revision ID: 0505_add_tech_fail_billable
Revises: 0504_fix_template_link
Create Date: 2026-02-23 00:00:00

"""
from alembic import op

revision = "0505_add_tech_fail_billable"
down_revision = "0504_fix_template_link"

NOTIFICATION_TECHNICAL_FAILURE_BILLABLE = "technical-failure-billable"

def upgrade():
    op.execute("INSERT INTO notification_status_types (name) VALUES ('{}')".format(NOTIFICATION_TECHNICAL_FAILURE_BILLABLE))


def downgrade():
    op.execute("DELETE FROM notification_status_types where name = '{}'".format(NOTIFICATION_TECHNICAL_FAILURE_BILLABLE))

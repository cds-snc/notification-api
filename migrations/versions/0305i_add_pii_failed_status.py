"""

Revision ID: 0305i_add_pii_failed_status
Revises: 0305h_smtp_columns
Create Date: 2020-01-02 11:24:58.773824

"""
from alembic import op


revision = '0305i_add_pii_failed_status'
down_revision = '0305h_smtp_columns'


def upgrade():
    op.execute("INSERT INTO notification_status_types (name) VALUES ('pii-check-failed')")


def downgrade():
    op.execute("DELETE FROM notification_status_types WHERE name = 'pii-check-failed'")

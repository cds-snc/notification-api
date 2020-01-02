"""

Revision ID: 0305i_add_pii_failed_status
Revises: 0305g_remove_letter_branding
Create Date: 2018-09-03 11:24:58.773824

"""
from alembic import op
import sqlalchemy as sa


revision = '0305i_add_pii_failed_status'
down_revision = '0305g_remove_letter_branding'


def upgrade():
    op.execute("INSERT INTO notification_status_types (name) VALUES ('pii-check-failed')")


def downgrade():
    op.execute("DELETE FROM notification_status_types WHERE name = 'pii-check-failed'")

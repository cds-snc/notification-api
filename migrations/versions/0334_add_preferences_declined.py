"""

Revision ID: 0334_add_preferences_declined
Revises: 0333b_update_history_comm_item
Create Date: 2021-08-24

"""
from alembic import op

revision = '0334_add_preferences_declined'
down_revision = '0333b_update_history_comm_item'


def upgrade():
    op.execute("insert into notification_status_types values ('preferences-declined')")


def downgrade():
    op.execute("delete from notification_status_types where name = 'preferences-declined'")

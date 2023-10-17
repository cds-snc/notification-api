"""

Revision ID: 0439_add_index_n_history
Revises: 0438_sms_templates_msgs_left
Create Date: 2023-10-05 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0439_add_index_n_history"
down_revision = "0438_sms_templates_msgs_left"

# option 1
def upgrade():
    op.execute("COMMIT")
    op.create_index(op.f("ix_notification_history_created_by_id"), "notification_history", ["created_by_id"], postgresql_concurrently=True)


def downgrade():
    op.drop_index(op.f("ix_notification_history_created_by_id"), table_name="notification_history")

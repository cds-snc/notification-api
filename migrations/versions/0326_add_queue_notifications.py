"""

Revision ID: 0326_add_queue_notifications
Revises: 0325_set_transaction_timeout
Create Date: 2021-07-29 17:30:00

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0326_add_queue_notifications"
down_revision = "0325_set_transaction_timeout"

user = "postgres"
timeout = 1200  # in seconds, i.e. 20 minutes


def upgrade():
    op.add_column("notifications", sa.Column("queue_name", sa.Text(), nullable=True))
    op.add_column("notification_history", sa.Column("queue_name", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("notifications", "queue_name")
    op.drop_column("notification_history", "queue_name")

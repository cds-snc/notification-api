"""Add created_by_id to scheduled_notifications so one-off notifications can be scheduled from the admin.

Revision ID: 0528_sched_notifs_created_by
Revises: 0527_jobs_billable_units
Create Date: 2026-11-17

One-off notifications sent from the admin have created_by_id set (and no api key). Scheduled ones need to keep it until
they're sent, so they're shown as sent by that user instead of by the API.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0528_sched_notifs_created_by"
down_revision = "0527_jobs_billable_units"

TABLE = "scheduled_notifications"


def upgrade():
    op.add_column(TABLE, sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("scheduled_notifications_created_by_id_fkey", TABLE, "users", ["created_by_id"], ["id"])


def downgrade():
    op.drop_constraint("scheduled_notifications_created_by_id_fkey", TABLE, type_="foreignkey")
    op.drop_column(TABLE, "created_by_id")

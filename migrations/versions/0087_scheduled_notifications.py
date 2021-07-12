"""empty message

Revision ID: 0087_scheduled_notifications
Revises: 0086_add_norm_to_notification
Create Date: 2017-05-15 12:50:20.041950

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0087_scheduled_notifications"
down_revision = "0086_add_norm_to_notification"


def upgrade():
    op.create_table(
        "scheduled_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("pending", sa.Boolean, nullable=False, default=True),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_scheduled_notifications_notification_id"),
        "scheduled_notifications",
        ["notification_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_scheduled_notifications_notification_id"),
        table_name="scheduled_notifications",
    )
    op.drop_table("scheduled_notifications")

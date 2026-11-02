"""Add columns to scheduled_notifications so scheduled one-off notifications can be stored there until they are sent.

Revision ID: 0526_sched_notifs_one_table
Revises: 0525_sync_template_hist_cat
Create Date: 2026-10-26

Scheduled one-off (API) notifications are inserted into notifications as soon as they are requested, so they are
counted on the day they were requested instead of the day they are sent (and can be timed out before being sent).
Their data will be kept in scheduled_notifications until their scheduled time, like scheduled bulk jobs, and
notification_id will be the id the notification will have once it is sent, so it no longer references notifications.

Schema only: existing (legacy) rows are unchanged and keep working. They're converted in a later migration.

Downgrading moves rows in the new format back to notifications.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0526_sched_notifs_one_table"
down_revision = "0525_sync_template_hist_cat"

TABLE = "scheduled_notifications"


def upgrade():
    op.drop_constraint("scheduled_notifications_notification_id_fkey", TABLE, type_="foreignkey")

    op.add_column(TABLE, sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(TABLE, sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(TABLE, sa.Column("template_version", sa.Integer(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "notification_type",
            postgresql.ENUM("email", "sms", "letter", name="notification_type", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(TABLE, sa.Column("to", sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column("_personalisation", sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(TABLE, sa.Column("key_type", sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column("client_reference", sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column("reply_to_text", sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column("billable_units", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(TABLE, sa.Column("created_at", sa.DateTime(), nullable=True))

    op.create_foreign_key("scheduled_notifications_service_id_fkey", TABLE, "services", ["service_id"], ["id"])
    op.create_foreign_key("scheduled_notifications_api_key_id_fkey", TABLE, "api_keys", ["api_key_id"], ["id"])
    op.create_foreign_key("scheduled_notifications_key_type_fkey", TABLE, "key_types", ["key_type"], ["name"])
    op.create_foreign_key(
        "scheduled_notifications_template_id_template_version_fkey",
        TABLE,
        "templates_history",
        ["template_id", "template_version"],
        ["id", "version"],
    )
    op.create_index(op.f("ix_scheduled_notifications_scheduled_for"), TABLE, ["scheduled_for"])
    op.create_index("ix_scheduled_notifications_service_id_scheduled_for", TABLE, ["service_id", "scheduled_for"])


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO notifications (
                id, service_id, template_id, template_version, notification_type, "to", _personalisation,
                api_key_id, key_type, client_reference, reply_to_text, billable_units, created_at, notification_status
            )
            SELECT
                notification_id, service_id, template_id, template_version, notification_type, "to", _personalisation,
                api_key_id, key_type, client_reference, reply_to_text, billable_units,
                COALESCE(created_at, now() AT TIME ZONE 'utc'), 'created'
            FROM scheduled_notifications
            WHERE service_id IS NOT NULL
            """
        )
    )
    # Orphaned legacy rows would violate the foreign key that's added back below
    conn.execute(
        sa.text(
            """
            DELETE FROM scheduled_notifications sn
            WHERE NOT EXISTS (SELECT 1 FROM notifications n WHERE n.id = sn.notification_id)
            """
        )
    )

    op.drop_index("ix_scheduled_notifications_service_id_scheduled_for", table_name=TABLE)
    op.drop_index(op.f("ix_scheduled_notifications_scheduled_for"), table_name=TABLE)
    op.drop_constraint("scheduled_notifications_template_id_template_version_fkey", TABLE, type_="foreignkey")
    op.drop_constraint("scheduled_notifications_key_type_fkey", TABLE, type_="foreignkey")
    op.drop_constraint("scheduled_notifications_api_key_id_fkey", TABLE, type_="foreignkey")
    op.drop_constraint("scheduled_notifications_service_id_fkey", TABLE, type_="foreignkey")
    for column in [
        "created_at",
        "billable_units",
        "reply_to_text",
        "client_reference",
        "key_type",
        "api_key_id",
        "_personalisation",
        "to",
        "notification_type",
        "template_version",
        "template_id",
        "service_id",
    ]:
        op.drop_column(TABLE, column)

    op.create_foreign_key("scheduled_notifications_notification_id_fkey", TABLE, "notifications", ["notification_id"], ["id"])

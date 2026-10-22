"""Store scheduled one-off notifications outside the notifications table until they are sent.

Revision ID: 0526_scheduled_one_off_notifs
Revises: 0525_sync_template_hist_cat
Create Date: 2026-10-22

Scheduled one-off (API) notifications used to be inserted into notifications as soon as they were requested, so they
were counted on the day they were requested instead of the day they were sent (and could be timed out before being
sent). They are now kept in scheduled_one_off_notifications until their scheduled time, like scheduled bulk jobs.

Any notifications that are still waiting to be sent are moved to the new table. The legacy scheduled_notifications
table is kept so that rows created by older API instances during a deploy are still sent.

Downgrading drops the table, so any scheduled one-off notifications that haven't been sent yet are lost.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0526_scheduled_one_off_notifs"
down_revision = "0525_sync_template_hist_cat"


def upgrade():
    op.create_table(
        "scheduled_one_off_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column(
            "notification_type",
            postgresql.ENUM("email", "sms", "letter", name="notification_type", create_type=False),
            nullable=False,
        ),
        sa.Column("to", sa.String(), nullable=False),
        sa.Column("_personalisation", sa.String(), nullable=True),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("key_type", sa.String(), nullable=False),
        sa.Column("client_reference", sa.String(), nullable=True),
        sa.Column("reply_to_text", sa.String(), nullable=True),
        sa.Column("billable_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["key_type"], ["key_types.name"]),
        sa.ForeignKeyConstraint(["template_id", "template_version"], ["templates_history.id", "templates_history.version"]),
    )
    op.create_index(
        op.f("ix_scheduled_one_off_notifications_scheduled_for"),
        "scheduled_one_off_notifications",
        ["scheduled_for"],
    )
    op.create_index(
        "ix_scheduled_one_off_notifications_service_id_scheduled_for",
        "scheduled_one_off_notifications",
        ["service_id", "scheduled_for"],
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO scheduled_one_off_notifications (
                id, service_id, template_id, template_version, notification_type, "to", _personalisation,
                api_key_id, key_type, client_reference, reply_to_text, billable_units, scheduled_for, created_at
            )
            SELECT
                n.id, n.service_id, n.template_id, n.template_version, n.notification_type, n."to", n._personalisation,
                n.api_key_id, n.key_type, n.client_reference, n.reply_to_text, COALESCE(n.billable_units, 0),
                sn.scheduled_for, n.created_at
            FROM scheduled_notifications sn
            JOIN notifications n ON n.id = sn.notification_id
            WHERE sn.pending AND n.notification_status = 'created'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM scheduled_notifications sn
            USING scheduled_one_off_notifications s
            WHERE sn.notification_id = s.id
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM notifications n
            USING scheduled_one_off_notifications s
            WHERE n.id = s.id
            """
        )
    )


def downgrade():
    op.drop_index("ix_scheduled_one_off_notifications_service_id_scheduled_for", table_name="scheduled_one_off_notifications")
    op.drop_index(op.f("ix_scheduled_one_off_notifications_scheduled_for"), table_name="scheduled_one_off_notifications")
    op.drop_table("scheduled_one_off_notifications")

"""Move pending scheduled one-off notifications out of the notifications table.

Revision ID: 0527_sched_notifs_move_rows
Revises: 0526_sched_notifs_one_table
Create Date: 2026-10-28

Pending legacy rows in scheduled_notifications (whose data is in notifications) are rewritten to the new format and
their notifications are deleted, so they're counted on the day they're sent. Rows that can't be sent (already
processed, or whose notification is gone or no longer in the created status) are deleted.

Rows that are due in the next few minutes, and rows written by older API instances during the deploy, keep the legacy
format: send-scheduled-notifications still sends those from the notifications table.

Downgrading is a no-op: rows in the new format are still sent, and 0526's downgrade moves them back to notifications.
"""

import sqlalchemy as sa
from alembic import op

revision = "0527_sched_notifs_move_rows"
down_revision = "0526_sched_notifs_one_table"


def upgrade():
    conn = op.get_bind()
    # Rows due soon are left in the legacy format, so they can't be sent by an older scheduler while they're rewritten
    conn.execute(
        sa.text(
            """
            UPDATE scheduled_notifications sn
            SET service_id = n.service_id,
                template_id = n.template_id,
                template_version = n.template_version,
                notification_type = n.notification_type,
                "to" = n."to",
                _personalisation = n._personalisation,
                api_key_id = n.api_key_id,
                key_type = n.key_type,
                client_reference = n.client_reference,
                reply_to_text = n.reply_to_text,
                billable_units = COALESCE(n.billable_units, 0),
                created_at = n.created_at
            FROM notifications n
            WHERE n.id = sn.notification_id
              AND sn.service_id IS NULL
              AND sn.pending
              AND n.notification_status = 'created'
              AND sn.scheduled_for > (now() AT TIME ZONE 'utc') + interval '10 minutes'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM notifications n
            USING scheduled_notifications sn
            WHERE n.id = sn.notification_id AND sn.service_id IS NOT NULL
            """
        )
    )
    # Only rows that can never be sent: rows written concurrently by older API instances must be kept
    conn.execute(
        sa.text(
            """
            DELETE FROM scheduled_notifications sn
            WHERE sn.service_id IS NULL
              AND (
                NOT sn.pending
                OR NOT EXISTS (
                    SELECT 1 FROM notifications n WHERE n.id = sn.notification_id AND n.notification_status = 'created'
                )
              )
            """
        )
    )


def downgrade():
    pass

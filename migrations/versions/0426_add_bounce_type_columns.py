"""empty message

Revision ID: 0426_add_bounce_type_columns
Revises: 0425_update_system_templates
Create Date: 2017-04-25 11:34:43.229494

"""

# revision identifiers, used by Alembic.
revision = "0426_add_bounce_type_columns"
down_revision = "0425_update_system_templates"

import sqlalchemy as sa
from alembic import op


# option 1
def upgrade():
    # 1 - add feedback types to notifications/notifications_history table
    feedback_types = sa.Enum("hard-bounce", "soft-bounce", name="notification_feedback_types")
    feedback_types.create(op.get_bind())
    op.add_column("notifications", sa.Column("feedback_type", feedback_types, nullable=True))
    op.add_column("notification_history", sa.Column("feedback_type", feedback_types, nullable=True))

    # 2 - add feedback sub types to notifications/notifications_history table
    feedback_subtypes = sa.Enum(
        "general",
        "no-email",
        "suppressed",
        "on-account-suppression-list",
        "mailbox-full",
        "message-too-large",
        "content-rejected",
        "attachment-rejected",
        name="notification_feedback_subtypes",
    )
    feedback_subtypes.create(op.get_bind())
    op.add_column("notifications", sa.Column("feedback_subtype", feedback_subtypes, nullable=True))
    op.add_column("notification_history", sa.Column("feedback_subtype", feedback_subtypes, nullable=True))

    # 3 - add ses_feedback_id to notifications/notifications_history table
    op.add_column("notifications", sa.Column("ses_feedback_id", sa.String(), nullable=True))
    op.add_column("notification_history", sa.Column("ses_feedback_id", sa.String(), nullable=True))

    # 4 - add ses_feedback_date to notifications/notifications_history table
    op.add_column("notifications", sa.Column("ses_feedback_date", sa.DateTime(), nullable=True))
    op.add_column("notification_history", sa.Column("ses_feedback_date", sa.DateTime(), nullable=True))


def downgrade():
    # 1 - drop feedback_type from notifications/notification_history table
    op.drop_column("notifications", "feedback_type")
    op.drop_column("notification_history", "feedback_type")
    op.get_bind()
    op.execute("DROP TYPE notification_feedback_types")

    # 2 - drop feedback_subtype from notifications/notification_history table
    op.drop_column("notifications", "feedback_subtype")
    op.drop_column("notification_history", "feedback_subtype")
    op.get_bind()
    op.execute("DROP TYPE notification_feedback_subtypes")

    # 3 - drop ses_feedback_id from notifications/notification_history table
    op.drop_column("notifications", "ses_feedback_id")
    op.drop_column("notification_history", "ses_feedback_id")

    # 4 - drop ses_feedback_date from notifications/notification_history table
    op.drop_column("notifications", "ses_feedback_date")
    op.drop_column("notification_history", "ses_feedback_date")

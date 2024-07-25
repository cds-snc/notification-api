"""empty message

Revision ID: 0427_add_bounce_type_indices
Revises: 0426_add_bounce_type_columns
Create Date: 2017-04-25 11:34:43.229494

"""

# revision identifiers, used by Alembic.
revision = "0427_add_bounce_type_indices"
down_revision = "0426_add_bounce_type_columns"

from alembic import op


# option 1
def upgrade():
    op.execute("COMMIT")
    op.create_index(op.f("ix_notifications_feedback_type"), "notifications", ["feedback_type"], postgresql_concurrently=True)
    op.create_index(
        op.f("ix_notification_history_feedback_type"), "notification_history", ["feedback_type"], postgresql_concurrently=True
    )


def downgrade():
    op.drop_index(op.f("ix_notifications_feedback_type"), table_name="notifications")
    op.drop_index(op.f("ix_notification_history_feedback_type"), table_name="notification_history")

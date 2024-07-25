"""empty message

Revision ID: 0428_add_bounce_type_known
Revises: 0427_add_bounce_type_indices
Create Date: 2017-04-25 11:34:43.229494

"""

# revision identifiers, used by Alembic.
revision = "0428_add_bounce_type_known"
down_revision = "0427_add_bounce_type_indices"

from alembic import op


# option 1
def upgrade():
    # prevent from being executed in a transaction block
    op.execute("COMMIT")

    op.execute("ALTER TYPE notification_feedback_types ADD VALUE 'unknown-bounce'")
    op.execute("ALTER TYPE notification_feedback_subtypes ADD VALUE 'unknown-bounce-subtype'")


def downgrade():
    sql = f"""DELETE FROM pg_enum
            WHERE enumlabel = 'unknown-bounce'
            AND enumtypid = (
              SELECT oid FROM pg_type WHERE typname = 'notification_feedback_types'
            )"""
    op.execute(sql)

    sql = f"""DELETE FROM pg_enum
            WHERE enumlabel = 'unknown-bounce-subtype'
            AND enumtypid = (
              SELECT oid FROM pg_type WHERE typname = 'notification_feedback_subtypes'
            )"""
    op.execute(sql)

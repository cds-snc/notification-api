"""

Revision ID: 0439_add_index_n_history
Revises: 0438_sms_templates_msgs_left
Create Date: 2023-10-05 00:00:00

"""
from datetime import datetime

from alembic import op

revision = "0444_add_index_n_history2"
down_revision = "0443_add_apikey_last_used_column"


def index_exists(name):
    connection = op.get_bind()
    result = connection.execute(
        "SELECT exists(SELECT 1 from pg_indexes where indexname = '{}') as ix_exists;".format(name)
    ).first()
    return result.ix_exists


# option 1
def upgrade():
    op.execute("COMMIT")
    if not index_exists("ix_notification_history_api_key_id_created"):
        op.create_index(
            op.f("ix_notification_history_api_key_id_created"),
            "notification_history",
            ["api_key_id", "created_at"],
            postgresql_concurrently=True,
        )


def downgrade():
    op.execute("COMMIT")
    op.drop_index(
        op.f("ix_notification_history_api_key_id_created"), table_name="notification_history", postgresql_concurrently=True
    )

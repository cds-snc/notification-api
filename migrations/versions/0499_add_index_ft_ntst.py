"""

Revision ID: 0499_add_index_ft_ntst
Revises: 0498_add_table_metadata
Create Date: 2025-12-02 00:00:00.000000

"""
from alembic import op

revision = '0499_add_index_ft_ntst'
down_revision = '0498_add_table_metadata'


def index_exists(name):
    connection = op.get_bind()
    result = connection.execute(
        "SELECT exists(SELECT 1 from pg_indexes where indexname = '{}') as ix_exists;".format(name)
    ).first()
    return result.ix_exists

def upgrade():
    # PostgreSQL requires that CREATE INDEX CONCURRENTLY cannot run within a transaction.
    # Alembic runs migrations in a transaction by default, so we need to commit the current
    # transaction before creating indexes concurrently.
    op.execute("COMMIT")
    if not index_exists("ix_ft_notification_status_stats_lookup"):
        # Covering index to optimize monthly stats aggregation queries
        # This supports the delivered-notifications-stats-by-month-data endpoint
        # INCLUDE clause allows index-only scans by including the aggregation columns
        op.execute("""
            CREATE INDEX CONCURRENTLY ix_ft_notification_status_stats_lookup 
            ON ft_notification_status (bst_date, notification_status, key_type)
            INCLUDE (notification_type, notification_count)
        """)


def downgrade():
    # PostgreSQL requires that DROP INDEX CONCURRENTLY cannot run within a transaction.
    # Need to commit the current transaction first.
    op.execute("COMMIT")
    if index_exists("ix_ft_notification_status_stats_lookup"):
        op.execute("DROP INDEX CONCURRENTLY ix_ft_notification_status_stats_lookup")

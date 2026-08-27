"""

Revision ID: 0501_seed_materialized_view
Revises: 0500_add_materialized_view
Create Date: 2025-12-11 00:00:00.000000

"""
from alembic import op

revision = '0501_seed_materialized_view'
down_revision = '0500_add_materialized_view'


def upgrade():
    # Seed the monthly_notification_stats table with historical data
    # Pre-aggregates delivered/sent notifications by month, service, and notification type
    # This will take approximately 7-10 seconds to complete
    # Aggregates from November 2019 (GC Notify start date) to present
    op.execute("""
        INSERT INTO monthly_notification_stats_summary (month, service_id, notification_type, notification_count, updated_at)
        SELECT 
            date_trunc('month', bst_date)::text as month,
            service_id,
            notification_type,
            sum(notification_count) as count,
            now() as updated_at
        FROM ft_notification_status
        WHERE key_type != 'test'
          AND notification_status IN ('delivered', 'sent')
          AND bst_date >= '2019-11-01'
        GROUP BY date_trunc('month', bst_date), service_id, notification_type
    """)


def downgrade():
    # Remove all seeded data from the table
    op.execute("DELETE FROM monthly_notification_stats_summary")

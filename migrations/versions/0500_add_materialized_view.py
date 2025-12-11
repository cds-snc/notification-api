"""

Revision ID: 0500_add_materialized_view
Revises: 0499_add_index_ft_ntst
Create Date: 2025-12-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0500_add_materialized_view'
down_revision = '0499_add_index_ft_ntst'


def upgrade():
    # Create summary table for monthly notification stats
    # This pre-aggregates data by month, service, and notification type
    # Significantly improves performance of the delivered-notifications-stats-by-month-data endpoint
    op.create_table(
        'monthly_notification_stats_summary',
        sa.Column('month', sa.Text(), nullable=False),
        sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('notification_type', sa.Text(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('month', 'service_id', 'notification_type', name='monthly_notification_stats_pkey')
    )
    
    # (Removed redundant index on month; primary key already provides this index)

    # Create index on notification_type for efficient querying
    op.create_index(
        'ix_monthly_notification_stats_notification_type',
        'monthly_notification_stats_summary',
        ['notification_type']
    )
    
    # Create index on updated_at for tracking stale data
    op.create_index(
        'ix_monthly_notification_stats_updated_at',
        'monthly_notification_stats_summary',
        ['updated_at']
    )

def downgrade():
    op.drop_table('monthly_notification_stats_summary')

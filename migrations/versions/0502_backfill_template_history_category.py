"""

Revision ID: 0502_backfill_template_history_category
Revises: 0501_seed_materialized_view
Create Date: 2026-01-09 00:00:00.000000

"""
from alembic import op

revision = '0502_backfill_template_history_category'
down_revision = '0501_seed_materialized_view'


def upgrade():
    # Backfill template_category_id in templates_history from templates table
    # Only updates the latest version of each template where category_id is NULL
    # This addresses templates that existed before the template_category_id field was added
    # and haven't been edited since then
    
    op.execute("""
        UPDATE templates_history th
        SET template_category_id = t.template_category_id
        FROM templates t
        WHERE th.id = t.id 
          AND th.version = t.version
          AND th.template_category_id IS NULL
          AND t.template_category_id IS NOT NULL
    """)


def downgrade():
    # Downgrade would set the backfilled values back to NULL
    # However, this is a data backfill migration, and rolling back would lose
    # the information about which records were backfilled vs. organically set
    # Leaving as a no-op since the data is correct either way
    pass

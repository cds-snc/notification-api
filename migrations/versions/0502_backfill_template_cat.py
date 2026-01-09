"""

Revision ID: 0502_backfill_template_cat
Revises: 0501_seed_materialized_view
Create Date: 2026-01-09 00:00:00.000000

"""
from alembic import op

revision = '0502_backfill_template_cat'
down_revision = '0501_seed_materialized_view'


def upgrade():
    # Backfill template_category_id in templates_history from templates table
    # Updates ALL versions of templates where category_id is NULL
    # This addresses templates that existed before the template_category_id field was added
    # Processes in chunks of 5000 to avoid database locks
    
    conn = op.get_bind()
    
    # Process in chunks until no more rows are affected
    while True:
        result = conn.execute("""
            UPDATE templates_history th
            SET template_category_id = t.template_category_id
            FROM templates t
            WHERE th.id = t.id 
              AND th.template_category_id IS NULL
              AND t.template_category_id IS NOT NULL
              AND th.ctid IN (
                  SELECT th2.ctid
                  FROM templates_history th2
                  JOIN templates t2 ON th2.id = t2.id
                  WHERE th2.template_category_id IS NULL
                    AND t2.template_category_id IS NOT NULL
                  LIMIT 5000
              )
        """)
        
        rows_updated = result.rowcount
        print(f"Updated {rows_updated} rows in templates_history")
        
        if rows_updated == 0:
            break


def downgrade():
    # Downgrade would set the backfilled values back to NULL
    # However, this is a data backfill migration, and rolling back would lose
    # the information about which records were backfilled vs. organically set
    # If needed, could set template_category_id to NULL for all history records
    # where it matches the current template's category_id, but this is not recommended
    pass

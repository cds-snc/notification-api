"""
Backfill template_category_id in templates_history from templates table.

Templates that have not been edited since template_category_id was added
are missing this value in their history rows. This migration copies the
template_category_id from the templates table to only the most recent version
of each template in templates_history where it is NULL.

Processes in batches of 1,000 rows to avoid locking issues on large tables.

Revision ID: 0502_backfill_template_category
Revises: 0501_seed_materialized_view
Create Date: 2026-01-09 00:00:00.000000

"""
from alembic import op
from sqlalchemy import text

revision = "0502_backfill_template_category"
down_revision = "0501_seed_materialized_view"

BATCH_SIZE = 1000


def upgrade():
    # Process in batches to avoid locking large table
    conn = op.get_bind()

    total_updated = 0
    while True:
        # Update only the most recent version of each template in history
        result = conn.execute(
            text("""
                WITH batch AS (
                    SELECT th.id, th.version
                    FROM templates_history th
                    JOIN templates t ON th.id = t.id AND th.version = t.version
                    WHERE th.template_category_id IS NULL
                      AND t.template_category_id IS NOT NULL
                    LIMIT :batch_size
                )
                UPDATE templates_history th
                SET template_category_id = t.template_category_id
                FROM templates t, batch
                WHERE th.id = batch.id
                  AND th.version = batch.version
                  AND th.id = t.id
            """),
            {"batch_size": BATCH_SIZE},
        )

        rows_updated = result.rowcount
        total_updated += rows_updated

        # Commit each batch to release locks
        conn.commit()

        if rows_updated == 0:
            break

    print(f"Backfilled template_category_id for {total_updated} templates_history rows")


def downgrade():
    # This is a data backfill - we don't revert it on downgrade
    # as the NULL values were unintentional gaps, not meaningful data
    pass

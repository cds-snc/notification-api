"""Sync template category between templates and current history rows.

Revision ID: 0525_sync_template_hist_cat
Revises: 0524_update_callback_susp_word
Create Date: 2026-08-20

This migration aligns templates_history.template_category_id with templates
for rows that represent the same template version (id + version).
"""

import sqlalchemy as sa
from alembic import op

revision = "0525_sync_template_hist_cat"
down_revision = "0524_update_callback_susp_word"


def upgrade():
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            UPDATE templates_history th
            SET template_category_id = t.template_category_id
            FROM templates t
            WHERE th.id = t.id
              AND th.version = t.version
              AND th.template_category_id IS DISTINCT FROM t.template_category_id
            """
        )
    )


def downgrade():
    # Data correction migration; no safe automatic rollback.
    pass

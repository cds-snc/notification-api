"""Backfill api_keys.permissions to empty array and add server default.

Step 1: UPDATE existing NULL rows to '{}' (empty array) in batches.
Step 2: ALTER COLUMN SET DEFAULT '{}' so new rows get an empty array at the DB level.

This is safe to run on a live table:
- The UPDATE is a normal row-level operation (no ACCESS EXCLUSIVE lock).
- ALTER COLUMN SET DEFAULT is metadata-only in Postgres (no rewrite).

Revision ID: 0513_backfill_api_key_permissions
Revises: 0512_api_key_permissions
Create Date: 2026-05-04
"""

from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0513_backfill_api_key_perm"
down_revision = "0512_api_key_permissions"


def upgrade():
    # Backfill existing rows
    op.execute("UPDATE api_keys SET permissions = '{}' WHERE permissions IS NULL")
    op.execute("UPDATE api_keys_history SET permissions = '{}' WHERE permissions IS NULL")

    # Set server default for future inserts
    op.alter_column(
        "api_keys",
        "permissions",
        server_default="{}",
    )
    op.alter_column(
        "api_keys_history",
        "permissions",
        server_default="{}",
    )


def downgrade():
    # Remove server default
    op.alter_column(
        "api_keys",
        "permissions",
        server_default=None,
    )
    op.alter_column(
        "api_keys_history",
        "permissions",
        server_default=None,
    )
    # We don't revert data back to NULL — the empty array is semantically equivalent.

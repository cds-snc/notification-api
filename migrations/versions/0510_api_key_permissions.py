"""Add permissions array column to api_keys and api_keys_history.

Stores per-API-key permission flags (e.g. "manage_templates") as a Postgres
text array. Validation of allowed values is enforced at the application layer
via app.models.API_KEY_PERMISSION_TYPES.

Revision ID: 0510_api_key_permissions
Revises: 0509_use_custom_unsub_url
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0510_api_key_permissions"
down_revision = "0509_use_custom_unsub_url"


def upgrade():
    # Nullable + no server_default so Postgres can add the column as a metadata-only
    # change without rewriting the table or taking a long ACCESS EXCLUSIVE lock.
    # Existing rows will read back as NULL; the model defaults new rows to [].
    op.add_column(
        "api_keys",
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=True,
        ),
    )
    op.add_column(
        "api_keys_history",
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("api_keys_history", "permissions")
    op.drop_column("api_keys", "permissions")

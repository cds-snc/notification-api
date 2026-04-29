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
    op.add_column(
        "api_keys",
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "api_keys_history",
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade():
    op.drop_column("api_keys_history", "permissions")
    op.drop_column("api_keys", "permissions")

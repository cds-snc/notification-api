"""
Revision ID: 0443_add_apikey_last_used_column
Revises: 0442_add_heartbeat_templates
Create Date: 2022-09-21 00:00:00
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0443_add_apikey_last_used_column"
down_revision = "0442_add_heartbeat_templates"


def upgrade():
    op.add_column("api_keys", sa.Column("last_used_timestamp", sa.DateTime(), nullable=True))
    op.add_column("api_keys_history", sa.Column("last_used_timestamp", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("api_keys", "last_used_timestamp")
    op.drop_column("api_keys_history", "last_used_timestamp")

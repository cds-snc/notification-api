"""

Revision ID: 0436_add_columns_api_keys
Revises: 0435_update_email_templates_2.py
Create Date: 2023-09-01

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0436_add_columns_api_keys"
down_revision = "0435_update_email_templates_2"

user = "postgres"
timeout = 60  # in seconds, i.e. 1 minute


def upgrade():
    op.add_column("api_keys", sa.Column("compromised_key_info", JSONB, nullable=True))
    op.add_column("api_keys_history", sa.Column("compromised_key_info", JSONB, nullable=True))


def downgrade():
    op.drop_column("api_keys", "compromised_key_info")
    op.drop_column("api_keys_history", "compromised_key_info")

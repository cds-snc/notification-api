"""

Revision ID: 0323_jobs_add_sender_id
Revises: 0322_jobs_add_api_key
Create Date: 2021-06-08 13:37:42

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0323_jobs_add_sender_id"
down_revision = "0322_jobs_add_api_key"


def upgrade():
    op.add_column("jobs", sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=True)),


def downgrade():
    op.drop_column("jobs", "sender_id")

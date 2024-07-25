"""

Revision ID: 0429_add_organisation_notes
Revises: 0428_add_bounce_type_known
Create Date: 2023-03-09 16:02:27.798584

"""
import sqlalchemy as sa
from alembic import op

revision = "0429_add_organisation_notes"
down_revision = "0428_add_bounce_type_known"

user = "postgres"
timeout = 1200  # in seconds, i.e. 20 minutes
default = 1


def upgrade():
    op.add_column(
        "services",
        sa.Column("organisation_notes", sa.String(), nullable=True),
    )
    op.add_column(
        "services_history",
        sa.Column("organisation_notes", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("services", "organisation_notes")
    op.drop_column("services_history", "organisation_notes")

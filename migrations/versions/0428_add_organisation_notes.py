"""

Revision ID: 0428_add_organisation_notes
Revises: 0427_add_bounce_type_indices
Create Date: 2023-03-06 00:00:00

"""
import sqlalchemy as sa
from alembic import op

revision = "0428_add_organisation_notes"
down_revision = "0427_add_bounce_type_indices"

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

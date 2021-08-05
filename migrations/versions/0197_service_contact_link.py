"""

Revision ID: 0197_service_contact_link
Revises: 0196_complaints_table
Create Date: 2018-05-31 15:01:32.977620

"""
import sqlalchemy as sa
from alembic import op

revision = "0197_service_contact_link"
down_revision = "0196_complaints_table"


def upgrade():
    op.add_column("services", sa.Column("contact_link", sa.String(length=255), nullable=True))
    op.add_column(
        "services_history",
        sa.Column("contact_link", sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column("services_history", "contact_link")
    op.drop_column("services", "contact_link")

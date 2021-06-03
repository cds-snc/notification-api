"""

Revision ID: 0179_billing_primary_const
Revises: 0178_add_filename
Create Date: 2018-03-13 14:52:40.413474

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0179_billing_primary_const"
down_revision = "0178_add_filename"


def upgrade():
    op.drop_column("ft_billing", "crown")
    op.drop_column("ft_billing", "annual_billing_id")
    op.drop_column("ft_billing", "organisation_id")
    op.drop_constraint("ft_billing_pkey", "ft_billing", type_="primary")
    # These are the orthogonal dimensions that define a row (except international).
    # These entries define a unique record.
    op.create_primary_key(
        "ft_billing_pkey",
        "ft_billing",
        ["bst_date", "template_id", "rate_multiplier", "provider", "international"],
    )


def downgrade():
    op.add_column(
        "ft_billing",
        sa.Column("organisation_id", postgresql.UUID(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "ft_billing",
        sa.Column("annual_billing_id", postgresql.UUID(), autoincrement=False, nullable=True),
    )
    op.add_column("ft_billing", sa.Column("crown", sa.TEXT(), autoincrement=False, nullable=True))
    op.drop_constraint("ft_billing_pkey", "ft_billing", type_="primary")
    op.create_primary_key("ft_billing_pkey", "ft_billing", ["bst_date", "template_id"])

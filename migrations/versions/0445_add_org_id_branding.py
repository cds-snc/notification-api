"""

Revision ID: 0445_add_org_id_branding
Revises: 0444_add_index_n_history2.py
Create Date: 2024-02-27

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0445_add_org_id_branding"
down_revision = "0444_add_index_n_history2"


def upgrade():
    op.add_column(
        "email_branding",
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_email_branding_organisation_id"),
        "email_branding",
        ["organisation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_email_branding_organisation",
        "email_branding",
        "organisation",
        ["organisation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("fk_organisation_agreement_user_id", "organisation", type_="foreignkey")

    op.create_foreign_key(
        "fk_organisation_agreement_signed_by",
        "organisation",
        "users",
        ["agreement_signed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_index(op.f("ix_email_branding_organisation_id"), table_name="email_branding")
    op.drop_constraint("fk_email_branding_organisation", "email_branding", type_="foreignkey")
    op.drop_column("email_branding", "organisation_id")

"""
Revision ID: 0446_add_alt_text.py
Revises: 0445_add_org_id_branding.py
Create Date: 2024-04-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0446_add_alt_text"
down_revision = "0445_add_org_id_branding"


def upgrade():
    table_description = op.get_bind().execute(
        text("SELECT * FROM information_schema.columns WHERE table_name = 'email_branding'")
    )

    # Check if the column exists
    if "alt_text_en" not in [column["column_name"] for column in table_description]:
        op.add_column(
            "email_branding",
            sa.Column("alt_text_en", sa.String(), nullable=True),
        )
    if "alt_text_fr" not in [column["column_name"] for column in table_description]:
        op.add_column(
            "email_branding",
            sa.Column("alt_text_fr", sa.String(), nullable=True),
        )


def downgrade():
    op.drop_column("email_branding", "alt_text_fr")
    op.drop_column("email_branding", "alt_text_en")

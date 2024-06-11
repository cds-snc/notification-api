"""

Revision ID: 0454_add_template_category
Revises: 0453_add_callback_failure_email
Create Date: 2024-06-11 13:32:00
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def upgrade():
    op.create_table(
        "template_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=False),
        sa.Column("name_fr", sa.String(length=255), nullable=False),
        sa.Column("description_en", sa.String(length=255), nullable=True),
        sa.Column("description_fr", sa.String(length=255), nullable=True),
        sa.Column("sms_process_type", sa.String(length=255), nullable=False),
        sa.Column("email_process_type", sa.String(length=255), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
    )

    op.add_column(
        "templates",
        sa.Colum("template_category_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        op.f("ix_template_category_id", "templates", ["template_category_id"], unique=False)
    )
    op.create_foreign_key(
        "fk_template_template_categories",
        "template",
        "template_category",
        ["template_category_id"],
        ["id"]
    )
    op.get_bind()

    # Insert the generic Low priority (bulk) category
    # op.execute("""
    #         INSERT INTO template_category (id, name_en, name_fr, sms_process_type, email_process_type, hidden)
    #         VALUES ('00000000-0000-0000-0000-000000000000', 'Low Category (Bulk)', 'Catégorie Basse (En Vrac)', true
    #     """
    # )

def downgrade():
    op.drop_constraint("fk_template_template_category", "templates", type_="foreignkey")
    op.drop_index(op.f("ix_template_category_id"), table_name="templates")
    op.drop_column("templates", "template_category_id")
    op.drop_table("template_category_id")
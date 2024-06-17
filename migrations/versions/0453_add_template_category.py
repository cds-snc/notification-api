"""

Revision ID: 0453_add_template_categories
Revises: 0452_set_pgaudit_config
Create Date: 2024-06-11 13:32:00
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from flask import current_app
from sqlalchemy.dialects import postgresql

revision = "0453_add_template_categories"
down_revision = "0452_set_pgaudit_config"


def upgrade():
    op.create_table(
        "template_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=False),
        sa.Column("name_fr", sa.String(length=255), nullable=False),
        sa.Column("description_en", sa.String(length=255), nullable=True),
        sa.Column("description_fr", sa.String(length=255), nullable=True),
        sa.Column("sms_process_type", sa.String(length=255), nullable=False),
        sa.Column("email_process_type", sa.String(length=255), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("name_en"),
        sa.UniqueConstraint("name_fr"),
    )

    op.add_column("templates", sa.Column("template_category_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("templates_history", sa.Column("template_category_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(
        op.f("ix_template_category_id"),
        "templates",
        ["template_category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_template_categories_name_en"),
        "template_categories",
        ["name_en"],
        unique=False,
    )
    op.create_index(
        op.f("ix_template_categories_name_fr"),
        "template_categories",
        ["name_fr"],
        unique=False,
    )
    op.create_foreign_key("fk_template_template_categories", "templates", "template_categories", ["template_category_id"], ["id"])

    # Insert the generic low, medium, and high categories
    op.execute(
        f"""
            INSERT INTO template_category (id, name_en, name_fr, sms_process_type, email_process_type, hidden)
            VALUES ({current_app.config['DEFAULT_TEMPLATE_CATEGORY_LOW']}, 'Low Category (Bulk)', 'Catégorie Basse (En Vrac)', true
        """
    )
    op.execute(
        f"""
            INSERT INTO template_category (id, name_en, name_fr, sms_process_type, email_process_type, hidden)
            VALUES ({current_app.config['DEFAULT_TEMPLATE_CATEGORY_MEDIUM']}, 'Medium Category (Normal)', 'Catégorie Moyenne (Normale)', true
        """
    )
    op.execute(
        f"""
            INSERT INTO template_category (id, name_en, name_fr, sms_process_type, email_process_type, hidden)
            VALUES ({current_app.config['DEFAULT_TEMPLATE_CATEGORY_HIGH']}, 'High Category (Priority)', 'Catégorie Haute (Priorité)', true
        """
    )


def downgrade():
    op.drop_constraint("fk_template_template_categories", "templates", type_="foreignkey")
    op.drop_index(op.f("ix_template_category_id"), table_name="templates")
    op.drop_index(op.f("ix_template_categories_name_en"), table_name="template_categories")
    op.drop_index(op.f("ix_template_categories_name_fr"), table_name="template_categories")
    op.drop_column("templates", "template_category_id")
    op.drop_column("templates_history", "template_category_id")
    op.drop_table("template_categories")

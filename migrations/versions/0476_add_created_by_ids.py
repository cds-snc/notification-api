"""

Revision ID: 0476_add_created_by_ids
Revises: 0475_change_notification_status
Create Date: 2025-02-11 15:37:00 EST

"""

from datetime import datetime
import uuid
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

from app.encryption import hashpw

revision = "0476_add_created_by_ids"
down_revision = "0475_change_notification_status"

missing_data_uuid = "00000000-0000-0000-0000-000000000000"


def upgrade():
    # Add a user to represent missing historical data
    password = hashpw(str(uuid.uuid4()))
    missing_data_user = """
        INSERT INTO users (id, name, email_address, created_at, failed_login_count, _password, mobile_number, password_changed_at, state, platform_admin, auth_type, password_expired, current_session_id, blocked)
        VALUES ('{}', 'Missing historical data', '{}', '{}', 0,'{}', NULL, '{}',  'inactive', False, 'email_auth', True, '{}', True)
    """
    now = datetime.utcnow()
    archived_email = "_archived_{}_good-luck@finding-what-you-need.ca".format(now.strftime("%Y-%m-%d"))
    op.execute(missing_data_user.format(missing_data_uuid, archived_email, now, password, now, missing_data_uuid))

    # === Template Categories
    op.add_column("template_categories", sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("template_categories", sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    # Back populate created_by_id for existing template categories with missing data user
    op.execute("UPDATE template_categories SET created_by_id = '{}'".format(missing_data_uuid))
    op.alter_column("template_categories", "created_by_id", nullable=False)
    op.create_foreign_key("template_categories_created_by_id_fkey", "template_categories", "users", ["created_by_id"], ["id"])
    op.create_index("ix_template_categories_created_by_id", "template_categories", ["created_by_id"])
    op.create_index("ix_template_categories_updated_by_id", "template_categories", ["updated_by_id"])

    # === Email Branding
    op.add_column("email_branding", sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    # Back populate with empty uuid to signal missing historical data
    op.execute(
        """
            UPDATE email_branding
            SET created_by_id = '{}'
        """.format(missing_data_uuid)
    )
    op.alter_column("email_branding", "created_by_id", nullable=False)
    op.create_foreign_key("email_branding_created_by_id_fkey", "email_branding", "users", ["created_by_id"], ["id"])
    op.create_index("ix_email_branding_created_by_id", "email_branding", ["created_by_id"])

    op.add_column("email_branding", sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True))
    op.execute("UPDATE email_branding SET created_at = '{}'".format("1970-01-01T00:00:00"))
    op.alter_column("email_branding", "created_at", nullable=False)

    op.add_column("email_branding", sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("email_branding_updated_by_id_fkey", "email_branding", "users", ["updated_by_id"], ["id"])
    op.create_index("ix_email_branding_updated_by_id", "email_branding", ["updated_by_id"])

    op.add_column("email_branding", sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True))


def downgrade():
    op.drop_index("ix_template_categories_created_by_id", table_name="template_categories")
    op.drop_index("ix_template_categories_updated_by_id", table_name="template_categories")
    op.drop_index("ix_email_branding_created_by_id", table_name="email_branding")
    op.drop_index("ix_email_branding_updated_by_id", table_name="email_branding")
    op.drop_constraint("template_categories_created_by_id_fkey", "template_categories", type_="foreignkey")
    op.drop_constraint("email_branding_created_by_id_fkey", "email_branding", type_="foreignkey")

    op.drop_column("email_branding", "updated_at")
    op.drop_column("email_branding", "updated_by_id")
    op.drop_column("email_branding", "created_at")
    op.drop_column("email_branding", "created_by_id")
    op.drop_column("template_categories", "created_by_id")
    op.drop_column("template_categories", "updated_by_id")

    op.execute("DELETE FROM USERS WHERE id = '{}'".format(missing_data_uuid))

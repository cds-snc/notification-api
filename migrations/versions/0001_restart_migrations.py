"""empty message

Revision ID: 0001_restart_migrations
Revises: None
Create Date: 2016-04-07 17:22:12.147542

"""

# revision identifiers, used by Alembic.
revision = "0001_restart_migrations"
down_revision = None

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "services",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("message_limit", sa.BigInteger(), nullable=False),
        sa.Column("restricted", sa.Boolean(), nullable=False),
        sa.Column("email_from", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_from"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("_password", sa.String(), nullable=False),
        sa.Column("mobile_number", sa.String(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column("logged_in_at", sa.DateTime(), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("platform_admin", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email_address"), "users", ["email_address"], unique=True)
    op.create_index(op.f("ix_users_name"), "users", ["name"], unique=False)
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("secret", sa.String(length=255), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret"),
        sa.UniqueConstraint("service_id", "name", name="uix_service_to_key_name"),
    )
    op.create_index(op.f("ix_api_keys_service_id"), "api_keys", ["service_id"], unique=False)
    op.create_table(
        "invited_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "cancelled", name="invited_users_status_types"),
            nullable=False,
        ),
        sa.Column("permissions", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invited_users_service_id"),
        "invited_users",
        ["service_id"],
        unique=False,
    )
    op.create_index(op.f("ix_invited_users_user_id"), "invited_users", ["user_id"], unique=False)
    op.create_table(
        "notification_statistics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day", sa.String(length=255), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("emails_requested", sa.BigInteger(), nullable=False),
        sa.Column("emails_delivered", sa.BigInteger(), nullable=False),
        sa.Column("emails_failed", sa.BigInteger(), nullable=False),
        sa.Column("sms_requested", sa.BigInteger(), nullable=False),
        sa.Column("sms_delivered", sa.BigInteger(), nullable=False),
        sa.Column("sms_failed", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", "day", name="uix_service_to_day"),
    )
    op.create_index(
        op.f("ix_notification_statistics_service_id"),
        "notification_statistics",
        ["service_id"],
        unique=False,
    )
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "permission",
            sa.Enum(
                "manage_users",
                "manage_templates",
                "manage_settings",
                "send_texts",
                "send_emails",
                "send_letters",
                "manage_api_keys",
                "platform_admin",
                "view_activity",
                name="permission_types",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", "user_id", "permission", name="uix_service_user_permission"),
    )
    op.create_index(op.f("ix_permissions_service_id"), "permissions", ["service_id"], unique=False)
    op.create_index(op.f("ix_permissions_user_id"), "permissions", ["user_id"], unique=False)
    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "template_type",
            sa.Enum("sms", "email", "letter", name="template_type"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject"),
    )
    op.create_index(op.f("ix_templates_service_id"), "templates", ["service_id"], unique=False)
    op.create_table(
        "user_to_service",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.UniqueConstraint("user_id", "service_id", name="uix_user_to_service"),
    )
    op.create_table(
        "verify_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("_code", sa.String(), nullable=False),
        sa.Column(
            "code_type",
            sa.Enum("email", "sms", name="verify_code_types"),
            nullable=False,
        ),
        sa.Column("expiry_datetime", sa.DateTime(), nullable=False),
        sa.Column("code_used", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_verify_codes_user_id"), "verify_codes", ["user_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_file_name", sa.String(), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in progress",
                "finished",
                "sending limits exceeded",
                name="job_status_types",
            ),
            nullable=False,
        ),
        sa.Column("notification_count", sa.Integer(), nullable=False),
        sa.Column("notifications_sent", sa.Integer(), nullable=False),
        sa.Column("processing_started", sa.DateTime(), nullable=True),
        sa.Column("processing_finished", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_service_id"), "jobs", ["service_id"], unique=False)
    op.create_index(op.f("ix_jobs_template_id"), "jobs", ["template_id"], unique=False)
    op.create_table(
        "template_statistics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_count", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_template_statistics_day"), "template_statistics", ["day"], unique=False)
    op.create_index(
        op.f("ix_template_statistics_service_id"),
        "template_statistics",
        ["service_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_template_statistics_template_id"),
        "template_statistics",
        ["template_id"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to", sa.String(), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("sent_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("sending", "delivered", "failed", name="notification_status_types"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_job_id"), "notifications", ["job_id"], unique=False)
    op.create_index(op.f("ix_notifications_reference"), "notifications", ["reference"], unique=False)
    op.create_index(
        op.f("ix_notifications_service_id"),
        "notifications",
        ["service_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_template_id"),
        "notifications",
        ["template_id"],
        unique=False,
    )
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_notifications_template_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_service_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_reference"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_job_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_template_statistics_template_id"), table_name="template_statistics")
    op.drop_index(op.f("ix_template_statistics_service_id"), table_name="template_statistics")
    op.drop_index(op.f("ix_template_statistics_day"), table_name="template_statistics")
    op.drop_table("template_statistics")
    op.drop_index(op.f("ix_jobs_template_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_service_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_verify_codes_user_id"), table_name="verify_codes")
    op.drop_table("verify_codes")
    op.drop_table("user_to_service")
    op.drop_index(op.f("ix_templates_service_id"), table_name="templates")
    op.drop_table("templates")
    op.drop_index(op.f("ix_permissions_user_id"), table_name="permissions")
    op.drop_index(op.f("ix_permissions_service_id"), table_name="permissions")
    op.drop_table("permissions")
    op.drop_index(
        op.f("ix_notification_statistics_service_id"),
        table_name="notification_statistics",
    )
    op.drop_table("notification_statistics")
    op.drop_index(op.f("ix_invited_users_user_id"), table_name="invited_users")
    op.drop_index(op.f("ix_invited_users_service_id"), table_name="invited_users")
    op.drop_table("invited_users")
    op.drop_index(op.f("ix_api_keys_service_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index(op.f("ix_users_name"), table_name="users")
    op.drop_index(op.f("ix_users_email_address"), table_name="users")
    op.drop_table("users")
    op.drop_table("services")
    ### end Alembic commands ###

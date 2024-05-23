"""

Revision ID: 0451_create_db_users
Revises: 0450_enable_pinpoint_provider
Create Date: 2024-05-23 12:00:00

"""
from alembic import op

revision = "0451_create_db_users"
down_revision = "0450_enable_pinpoint_provider"

super_role = "rds_superuser"
roles = ["app_db_user", "quicksight_db_user"]
database_name = op.get_bind().engine.url.database  # database name that the migration is being run on


def upgrade():
    # Skip this migration in the test database as there are multiple test databases that are created.
    # This leads to a race condition attempting to alter the same users\ multiple times and causes
    # sporadic unit test failures.
    if "test_notification_api" in database_name:
        return

    for role in roles:
        create_role_if_not_exist(role)
        op.execute(f"CREATE ROLE {role};")
        op.execute(f"GRANT {role} TO {super_role} WITH ADMIN OPTION;")


def create_role_if_not_exist(role):
    """
    Makes sure the expected user exists in the database before performing the ALTER USER operation.
    If the user already exists, nothing happens.  This is needed so that the migrations can be
    run on localhost where the users do not exist.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
        CREATE ROLE {role};
        EXCEPTION WHEN duplicate_object THEN RAISE NOTICE '%, skipping', SQLERRM USING ERRCODE = SQLSTATE;
        END
        $$;
    """
    )

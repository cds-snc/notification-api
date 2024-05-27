"""

Revision ID: 0452_set_pgaudit_config
Revises: 0451_create_db_users
Create Date: 2024-05-27 12:00:00

"""
from alembic import op

revision = "0452_set_pgaudit_config"
down_revision = "0451_create_db_users"

users = ["app_db_user", "rdsproxyadmin"]
database_name = op.get_bind().engine.url.database  # database name that the migration is being run on


def upgrade():
    # Skip this migration in the test database as there are multiple test databases that are created.
    # This leads to a race condition attempting to alter the same users multiple times and causes
    # sporadic unit test failures.
    if "test_notification_api" in database_name:
        return

    for user in users:
        create_user_if_not_exists(user)
        op.execute(f"ALTER USER {user} SET pgaudit.log TO 'NONE'")


def downgrade():
    if "test_notification_api" in database_name:
        return

    # Reset the pgaudit.log setting
    for user in users:
        op.execute(f"ALTER USER {user} RESET pgaudit.log")


def create_user_if_not_exists(user):
    """
    Makes sure the expected user exists in the database before performing the ALTER USER operation.
    If the user already exists, nothing happens.  This is needed so that the migrations can be
    run on localhost where the users do not exist.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
        CREATE USER {user};
        EXCEPTION WHEN duplicate_object THEN RAISE NOTICE '%, skipping', SQLERRM USING ERRCODE = SQLSTATE;
        END
        $$;
    """
    )

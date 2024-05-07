"""

Revision ID: 0449_set_pgaudit_config
Revises: 0448_update_verify_code2
Create Date: 2024-05-07 16:30:00

"""
from alembic import op

revision = "0449_set_pgaudit_config"
down_revision = "0448_update_verify_code2"

roles = ["app_db_user", "rdsproxyadmin"]
database_name = op.get_bind().engine.url.database  # database name that the migration is being run on


def upgrade():
    for role in roles:
        op.execute(f"ALTER ROLE {role} IN DATABASE {database_name} SET pgaudit.log TO 'NONE'")


def downgrade():
    for role in roles:
        op.execute(f"ALTER ROLE {role} IN DATABASE {database_name} RESET pgaudit.log")

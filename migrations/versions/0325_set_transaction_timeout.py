"""

Revision ID: 0325_set_transaction_timeout
Revises: 0325_set_transaction_timeout
Create Date: 2021-07-29 17:30:00

"""
from alembic import op

revision = "0325_set_transaction_timeout"
down_revision = "0324_fix_template_redacted"

user = "postgres"
timeout = 1200  # in seconds, i.e. 20 minutes
database_name = op.get_bind().engine.url.database  # database name that the migration is being run on


def upgrade():
    op.execute(f"ALTER ROLE {user} IN DATABASE {database_name} SET statement_timeout = '{timeout}s'")


def downgrade():
    op.execute(f"ALTER ROLE {user} IN DATABASE {database_name} RESET statement_timeout")

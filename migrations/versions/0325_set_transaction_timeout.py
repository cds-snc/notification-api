"""

Revision ID: 0323_jobs_add_sender_id
Revises: 0322_jobs_add_api_key
Create Date: 2021-06-08 13:37:42

"""
from alembic import op

revision = "0325_set_transaction_timeout"
down_revision = "0324_fix_template_redacted"

user = "postgres"
timeout = 1200  # in seconds, i.e. 20 minutes


def upgrade():
    op.execute(f"ALTER ROLE {user} SET statement_timeout = '{timeout}s'")


def downgrade():
    op.execute(f"ALTER ROLE {user} RESET statement_timeout")

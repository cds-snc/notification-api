"""

Revision ID: 0473_broken_migration
Revises: 0472_add_direct_email_2
Create Date: 2025-01-21 19:45:54.021107

"""
from alembic import op

revision = "0473_broken_migration"
down_revision = "0472_add_direct_email_2"


def upgrade():
    conn = op.get_bind()
    conn.execute("ALTER TABLE no_such_table ALTER COLUMN nope SET DEFAULT 0")


def downgrade():
    pass

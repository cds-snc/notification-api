"""

Revision ID: 0485_security_key_auth
Revises: 0484_users_migrations
Create Date: 2025-07-04 00:00:00.000000

"""
from alembic import op

revision = '0485_security_key_auth'
down_revision = '0484_users_migrations'


def upgrade():
    op.execute("INSERT INTO auth_type VALUES ('security_key_auth')")
    

def downgrade():
    op.execute("DELETE FROM auth_type WHERE name = 'security_key_auth'")

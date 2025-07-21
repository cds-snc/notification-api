"""

Revision ID: 0486_user_security_key
Revises: 0485_security_key_auth
Create Date: 2025-07-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0486_user_security_key'
down_revision = '0485_security_key_auth'


def upgrade():
    op.add_column('users', sa.Column('fido2_key_id', postgresql.UUID(as_uuid=True), nullable=True))

def downgrade():
    op.drop_column('users', 'fido2_key_id')

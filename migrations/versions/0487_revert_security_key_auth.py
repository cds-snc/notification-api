"""

Revision ID: 0487_revert_security_key_auth
Revises: 0486_user_security_key
Create Date: 2025-07-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0487_revert_security_key_auth'
down_revision = '0486_user_security_key'


def upgrade():
    op.drop_column('users', 'fido2_key_id')

def downgrade():
    op.add_column('users', sa.Column('fido2_key_id', postgresql.UUID(as_uuid=True), nullable=True))

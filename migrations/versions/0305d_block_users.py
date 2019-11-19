"""

Revision ID: 0305d_block_users
Revises: 0305c_login_events
Create Date: 2019-11-15 16:07:22.019759

"""
from alembic import op
import sqlalchemy as sa


revision = '0305d_block_users'
down_revision = '0305c_login_events'


def upgrade():
    op.add_column('users', sa.Column('blocked', sa.BOOLEAN(), nullable=False,  server_default=sa.false()))

def downgrade():
    op.drop_column('users', 'blocked')

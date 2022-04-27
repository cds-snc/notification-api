"""
Revision ID: 0343_create_VAProfileLocalCache
Revises: 0342_add_reply_to_field
Create Date: 2022-04-06 21:54:43.488085
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0343_create_VAProfileLocalCache'
down_revision = '0342_add_reply_to_field'


def upgrade():
    op.create_table(
        'va_profile_local_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mpi_icn', sa.String(length=29), nullable=False),
        sa.Column('va_profile_id', sa.Integer(), nullable=False),
        sa.Column('va_profile_item_id', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('va_profile_local_cache')


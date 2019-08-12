"""

Revision ID: 0301b_fido2_table
Revises: 0301a_merge_heads
Create Date: 2019-08-09 16:07:22.019759

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0301b_fido2_table'
down_revision = '0301a_merge_heads'


def upgrade():
    op.create_table(
        'fido2_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_fido2_keys_user_id'), 'fido2_keys', ['user_id'], unique=False)

    op.create_table(
        'fido2_sessions',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.Column('session', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

def downgrade():
    op.execute('DROP TABLE fido2_keys')
    op.execute('DROP TABLE fido2_sessions')

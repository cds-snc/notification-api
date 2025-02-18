"""
Revision ID: 0376_drop_reply_to
Revises: 0375_add_key_revoked
Create Date: 2025-01-31 19:25:59.411624
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0376_drop_reply_to'
down_revision = '0375_add_key_revoked'


def upgrade():
    op.drop_index('ix_service_email_reply_to_service_id', table_name='service_email_reply_to')
    op.drop_table('service_email_reply_to')


def downgrade():
    op.create_table('service_email_reply_to',
        sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
        sa.Column('service_id', postgresql.UUID(), autoincrement=False, nullable=False),
        sa.Column('email_address', sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column('is_default', sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
        sa.Column('archived', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], name='service_email_reply_to_service_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='service_email_reply_to_pkey')
    )
    op.create_index('ix_service_email_reply_to_service_id', 'service_email_reply_to', ['service_id'], unique=False)

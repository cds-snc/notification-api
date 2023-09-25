"""

Revision ID: 0363_add_reply_to_inbox
Revises: 0362_add_service_field
Create Date: 2023-09-20 19:58:37.246845

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0363_add_reply_to_inbox'
down_revision = '0362_add_service_field'


def upgrade():
    op.create_table('reply_to_inbox',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('inbox', sa.String(), nullable=False),
    sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['service_id'], ['services.id']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reply_to_inbox_service_id'), 'reply_to_inbox', ['service_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_reply_to_inbox_service_id'), table_name='reply_to_inbox')
    op.drop_table('reply_to_inbox')

"""

Revision ID: 0478_update_reports_table
Revises: 0477_add_created_by_ids
Create Date: 2025-04-07 23:44:02.031724

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0478_update_reports_table'
down_revision = '0477_add_created_by_ids'


def upgrade():
    op.add_column('reports', sa.Column('language', sa.String(length=2), nullable=True))
    op.alter_column('reports', 'url',
               existing_type=sa.VARCHAR(length=255),
               type_=sa.String(length=800),
               existing_nullable=True)


def downgrade():
    op.alter_column('reports', 'url',
               existing_type=sa.String(length=800),
               type_=sa.VARCHAR(length=255),
               existing_nullable=True)
    op.drop_column('reports', 'language')
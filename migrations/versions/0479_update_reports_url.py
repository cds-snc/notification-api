"""

Revision ID: 0479_update_reports_url
Revises: 0478_update_reports_table
Create Date: 2025-04-08 18:38:52.786361

"""
from alembic import op
import sqlalchemy as sa

revision = '0479_update_reports_url'
down_revision = '0478_update_reports_table'


def upgrade():
    op.alter_column('reports', 'url',
               existing_type=sa.VARCHAR(length=800),
               type_=sa.String(length=2000),
               existing_nullable=True)

def downgrade():
    op.alter_column('reports', 'url',
               existing_type=sa.String(length=2000),
               type_=sa.VARCHAR(length=800),
               existing_nullable=True)

"""

Revision ID: 0478_add_report_language
Revises: 0477_add_created_by_ids
Create Date: 2025-04-01 19:24:10.080163

"""
from alembic import op
import sqlalchemy as sa

revision = '0478_add_report_language'
down_revision = '0477_add_created_by_ids'


def upgrade():
    op.add_column('reports', sa.Column('language', sa.String(length=2), nullable=False))

def downgrade():
    op.drop_column('reports', 'language')

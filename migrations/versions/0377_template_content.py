"""
Revision ID: 0377_template_content
Revises: 0376_drop_reply_to
Create Date: 2025-02-25 15:12:25.067224
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0377_template_content'
down_revision = '0376_drop_reply_to'


def upgrade():
    op.add_column('templates', sa.Column('content_as_html', sa.Text(), nullable=True))
    op.add_column('templates', sa.Column('content_as_plain_text', sa.Text(), nullable=True))
    op.add_column('templates_history', sa.Column('content_as_html', sa.Text(), nullable=True))
    op.add_column('templates_history', sa.Column('content_as_plain_text', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('templates_history', 'content_as_plain_text')
    op.drop_column('templates_history', 'content_as_html')
    op.drop_column('templates', 'content_as_plain_text')
    op.drop_column('templates', 'content_as_html')

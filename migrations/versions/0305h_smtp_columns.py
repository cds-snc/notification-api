"""

Revision ID: 0305h_smtp_columns
Revises: 0305g_remove_letter_branding
Create Date: 2019-12-13 17:08:21.019759

"""
import sqlalchemy as sa
from alembic import op

revision = '0305h_smtp_columns'
down_revision = '0305g_remove_letter_branding'

def upgrade():
    op.add_column('services', sa.Column('smtp_user', sa.Text(), nullable=True))
    op.add_column('services_history', sa.Column('smtp_user', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('services', 'smtp_user')
    op.drop_column('services_history', 'smtp_user')

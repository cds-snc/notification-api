"""
Revision ID: 0489_add_suspended_columns
Revises: 0488_update_2fa_templates
Create Date: 2025-10-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0489_add_suspended_columns'
down_revision = '0488_update_2fa_templates'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('services', sa.Column('suspended_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('services', sa.Column('suspended_at', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('services', 'suspended_by_id')
    op.drop_column('services', 'suspended_at')
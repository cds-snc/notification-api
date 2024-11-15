"""

Revision ID: 0374_add_expected_cadence
Revises: 0373_va_profile_notification
Create Date: 2024-11-13 18:59:38.418467

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0374_add_expected_cadence'
down_revision = '0373_va_profile_notification'


def upgrade():
    op.add_column('promoted_templates', sa.Column('expected_cadence', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('promoted_templates', 'expected_cadence')

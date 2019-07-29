"""

Revision ID: 0300a_merge_heads
Revises: 0298c_replace_name_in_history, 0300_migrate_org_types
Create Date: 2019-07-29 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = '0300a_merge_heads'
down_revision = ('0298c_replace_name_in_history', '0300_migrate_org_types')
branch_labels = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    pass


def downgrade():
    pass
"""

Revision ID: 0303a_merge
Revises: 0303_populate_services_org_id, 0302a_merge
Create Date: 2019-07-29 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = '0303a_merge'
down_revision = ('0303_populate_services_org_id', '0302a_merge')
branch_labels = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    pass


def downgrade():
    pass
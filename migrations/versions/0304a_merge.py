"""

Revision ID: 0304a_merge
Revises: 0304_remove_org_to_service, 0303a_merge
Create Date: 2019-07-29 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = "0304a_merge"
down_revision = ("0304_remove_org_to_service", "0303a_merge")
branch_labels = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    pass


def downgrade():
    pass

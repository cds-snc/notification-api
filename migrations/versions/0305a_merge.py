"""

Revision ID: 0305a_merge
Revises: 0305_add_gp_org_type, 0304a_merge
Create Date: 2019-09-04 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = "0305a_merge"
down_revision = ("0305_add_gp_org_type", "0304a_merge")
branch_labels = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    pass


def downgrade():
    pass

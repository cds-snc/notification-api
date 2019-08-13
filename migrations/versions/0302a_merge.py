"""

Revision ID: 0302a_merge
Revises: 0301c_update_golive_template, 0302_add_org_id_to_services
Create Date: 2019-07-29 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = '0302a_merge'
down_revision = ('0301c_update_golive_template', '0302_add_org_id_to_services')
branch_labels = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    pass


def downgrade():
    pass
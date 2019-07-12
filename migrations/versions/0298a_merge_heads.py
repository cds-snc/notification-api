"""

Revision ID: 0298a_merge_heads
Revises: 0297c_change_primary_user, 0298_add_mou_signed_receipt
Create Date: 2014-11-20 13:31:50.811663

"""

# revision identifiers, used by Alembic.
revision = '0298a_merge_heads'
down_revision = ('0297c_change_primary_user', '0298_add_mou_signed_receipt')
branch_labels = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    pass


def downgrade():
    pass
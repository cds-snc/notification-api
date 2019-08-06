"""

Revision ID: 0301a_merge_heads
Revises: 0300e_account_change_email, 0301_upload_letters_permission
Create Date: 2019-07-29 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = '0301a_merge_heads'
down_revision = ('0300e_account_change_email', '0301_upload_letters_permission')
branch_labels = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    pass


def downgrade():
    pass
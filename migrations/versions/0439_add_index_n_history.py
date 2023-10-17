"""

Revision ID: 0439_add_index_n_history
Revises: 0438_sms_templates_msgs_left
Create Date: 2023-10-05 00:00:00

"""
from datetime import datetime

from alembic import op

revision = "0439_add_index_n_history"
down_revision = "0438_sms_templates_msgs_left"


# Decided against adding this index in prd as the table is too large and needs more testing
def upgrade():
    pass


def downgrade():
    pass

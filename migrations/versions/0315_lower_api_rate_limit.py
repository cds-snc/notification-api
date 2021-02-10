"""

Revision ID: 0315_lower_api_rate_limit
Revises: 0314_no_reply_template
Create Date: 2021-01-08 16:13:25

"""
from alembic import op
import sqlalchemy as sa


revision = '0315_lower_api_rate_limit'
down_revision = '0314_no_reply_template'

def upgrade():
    op.execute("ALTER TABLE services ALTER rate_limit DROP DEFAULT")
    op.execute("ALTER TABLE services_history ALTER rate_limit DROP DEFAULT")

def downgrade():
    op.execute("ALTER TABLE services ALTER rate_limit SET DEFAULT '1000'")
    op.execute("ALTER TABLE services_history ALTER rate_limit SET DEFAULT '1000'")

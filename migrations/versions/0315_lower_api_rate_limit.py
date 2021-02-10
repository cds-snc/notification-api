"""

Revision ID: 0315_lower_api_rate_limit
Revises: 0314_no_reply_template
Create Date: 2021-01-08 16:13:25

"""
from alembic import op

revision = '0315_lower_api_rate_limit'
down_revision = '0314_no_reply_template'

def upgrade():
    op.execute("ALTER TABLE services ALTER rate_limit SET DEFAULT '1000'")
    op.execute("ALTER TABLE services_history ALTER rate_limit SET DEFAULT '1000'")
    op.execute("UPDATE TABLE services SET rate_limit = '1000' WHERE rate_limit = '3000'")

def downgrade():
    op.execute("ALTER TABLE services ALTER rate_limit SET DEFAULT '3000'")
    op.execute("ALTER TABLE services_history ALTER rate_limit SET DEFAULT '3000'")
    op.execute("UPDATE TABLE services SET rate_limit = '3000' WHERE rate_limit = '1000'"

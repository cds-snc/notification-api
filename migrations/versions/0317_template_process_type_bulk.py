"""

Revision ID: 0317_template_process_type_bulk
Revises: 0316_now_live_template
Create Date: 2021-04-12 13:37:42

"""
from alembic import op

revision = '0317_template_process_type_bulk'
down_revision = '0316_now_live_template'


def upgrade():
    op.execute("INSERT INTO template_process_type VALUES ('bulk')")


def downgrade():
    op.execute("DELETE FROM template_process_type WHERE name = 'bulk'")

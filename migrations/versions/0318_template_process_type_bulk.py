"""

Revision ID: 0318_template_process_type_bulk
Revises: 0317_add_provider_response
Create Date: 2021-04-12 13:37:42

"""
from alembic import op

revision = '0318_template_process_type_bulk'
down_revision = '0317_add_provider_response'


def upgrade():
    op.execute("INSERT INTO template_process_type VALUES ('bulk')")


def downgrade():
    op.execute("DELETE FROM template_process_type WHERE name = 'bulk'")

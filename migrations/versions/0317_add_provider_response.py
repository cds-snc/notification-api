"""

Revision ID: 0317_add_provider_response
Revises: 0316_now_live_template
Create Date: 2016-04-15 12:12:46.383782

"""

revision = '0317_add_provider_response'
down_revision = '0316_now_live_template'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('notifications', sa.Column('provider_response', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('notifications', 'provider_response')

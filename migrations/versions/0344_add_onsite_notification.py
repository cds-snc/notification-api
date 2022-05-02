"""
Revision ID: 0344_add_onsite_notification
Revises: 0343_create_VAProfileLocalCache
Create Date: 2022-04-20 15:17:14.050637
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0344_add_onsite_notification'
down_revision = '0343_create_VAProfileLocalCache'


def upgrade():
    # Without the "server_default" parameter, this migration causes a database integrity error.
    #   https://github.com/miguelgrinberg/Flask-Migrate/issues/254
    op.add_column('templates', sa.Column('onsite_notification', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('templates_history', sa.Column('onsite_notification', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('templates_history', 'onsite_notification')
    op.drop_column('templates', 'onsite_notification')


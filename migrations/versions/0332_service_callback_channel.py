"""

Revision ID: 0332_service_callback_channel
Revises: 0331b_status_and_callback_types
Create Date: 2021-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = '0332_service_callback_channel'
down_revision = '0331b_status_and_callback_types'


def upgrade():
    op.create_table('service_callback_channel',
                    sa.Column('channel', sa.String(), nullable=False),
                    sa.PrimaryKeyConstraint('channel')
                    )
    op.execute("insert into service_callback_channel values ('webhook'), ('queue')")
    op.add_column('service_callback', sa.Column('callback_channel', sa.String(), nullable=True))
    op.create_foreign_key('service_callback_channel_fk',
                          'service_callback',
                          'service_callback_channel',
                          ['callback_channel'],
                          ['channel']
                          )
    op.add_column('service_callback_history', sa.Column('callback_channel', sa.String(), nullable=True))


def downgrade():
    op.drop_column('service_callback_history', 'callback_channel')
    op.drop_constraint('service_callback_channel_fk', 'service_callback_channel', type_='foreignkey')
    op.drop_column('service_callback', 'callback_channel')
    op.drop_table('service_callback_channel')

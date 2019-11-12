"""

Revision ID: 0305c_login_events
Revises: 0305b_branding_request_template
Create Date: 2019-08-09 16:07:22.019759

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0305c_login_events'
down_revision = '0305b_branding_request_template'


def upgrade():
    op.create_table(
        'login_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.Column('data', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_login_events_user_id'), 'login_events', ['user_id'], unique=False)

def downgrade():
    op.execute('DROP TABLE fido2_keys')

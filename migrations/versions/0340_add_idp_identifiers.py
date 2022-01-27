"""

Revision ID: 0340_add_idp_identifiers
Revises: 0339_add_push_notif_permission
Create Date: 2022-01-24 18:06:31.696656

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0340_add_idp_identifiers'
down_revision = '0339_add_push_notif_permission'


def upgrade():
    op.create_table('users_idp_ids',
                    sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column('idp_name', sa.String(), nullable=False),
                    sa.Column('idp_id', sa.String(), nullable=False),
                    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='cascade'),
                    sa.PrimaryKeyConstraint('user_id', 'idp_name')
                    )
    op.create_index('ix_users_idp_ids_idp_name_idp_id', 'users_idp_ids', ['idp_name', 'idp_id'], unique=True)
    op.execute((
        "INSERT INTO users_idp_ids (user_id, idp_name, idp_id)"
        "SELECT id, 'github', identity_provider_user_id FROM users WHERE identity_provider_user_id IS NOT NULL"
    ))


def downgrade():
    op.drop_index('ix_users_idp_ids_idp_name_idp_id', table_name='users_idp_ids')
    op.drop_table('users_idp_ids')

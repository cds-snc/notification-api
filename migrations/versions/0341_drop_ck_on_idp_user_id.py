"""

Revision ID: 0341_drop_ck_on_idp_user_id
Revises: 0340_add_idp_identifiers
Create Date: 2022-01-26 12:21:31.096971

"""
from alembic import op

revision = '0341_drop_ck_on_idp_user_id'
down_revision = '0340_add_idp_identifiers'


def upgrade():
    op.drop_constraint('ck_users_password_or_identity_provider_user_id', 'users')


def downgrade():
    op.create_check_constraint(
        'ck_users_password_or_identity_provider_user_id',
        'users',
        "_password is not null or identity_provider_user_id is not null"
    )

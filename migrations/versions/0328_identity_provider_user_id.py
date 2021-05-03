"""

Revision ID: 0328_identity_provider_user_id
Revises: 0327_update_notify_service_user
Create Date: 2021-05-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.functions import current_timestamp

revision = '0328_identity_provider_user_id'
down_revision = '0327_update_notify_service_user'


def upgrade():
    op.alter_column('users', '_password', nullable=True, server_default=None)
    op.alter_column('users', 'password_changed_at', nullable=True, server_default=None)
    op.alter_column('users', 'auth_type', nullable=True, server_default=None)

    op.add_column('users', sa.Column('identity_provider_user_id', sa.String(), nullable=True))
    op.create_unique_constraint('users_identity_provider_user_id', 'users', ['identity_provider_user_id'])

    op.drop_constraint('ck_users_mobile_or_email_auth', 'users')

    op.create_check_constraint(
        'ck_users_mobile_number_if_sms_auth',
        'users',
        "auth_type != 'sms_auth' or mobile_number is not null"
    )

    op.create_check_constraint(
        'ck_users_password_or_identity_provider_user_id',
        'users',
        "_password is not null or identity_provider_user_id is not null"
    )


def downgrade():
    op.execute("UPDATE users SET _password='fake_password' WHERE _password IS NULL;")
    op.execute(f"UPDATE users SET password_changed_at={current_timestamp()} WHERE password_changed_at IS NULL;")
    op.execute("UPDATE users SET auth_type='email_auth' WHERE auth_type IS NULL;")

    op.alter_column('users', '_password', nullable=False)
    op.alter_column('users', 'password_changed_at', nullable=False)
    op.alter_column('users', 'auth_type', nullable=False, server_default='sms_auth')

    op.drop_column('users', 'identity_provider_user_id')
    op.drop_constraint('users_identity_provider_user_id', 'users')

    op.drop_constraint('ck_users_mobile_number_if_sms_auth', 'users')
    op.drop_constraint('ck_users_password_or_identity_provider_user_id', 'users')

    op.create_check_constraint(
        'ck_users_mobile_or_email_auth',
        'users',
        "auth_type = 'email_auth' or mobile_number is not null"
    )

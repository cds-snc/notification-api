"""
Revision ID: 0488_update_user_auth_constraint
Revises: 0487_revert_security_key_auth
Create Date: 2025-07-22 00:00:00.000000
"""

from alembic import op

revision = '0487_update_user_auth_constraint'
down_revision = '0487_revert_security_key_auth'

def upgrade():
    op.drop_constraint('ck_users_mobile_or_email_auth', 'users', type_='check')
    op.create_check_constraint(
        'ck_users_mobile_or_email_auth',
        'users',
        "(auth_type IN ('email_auth', 'security_key_auth') OR mobile_number IS NOT NULL)"
    )

def downgrade():
    op.drop_constraint('ck_users_mobile_or_email_auth', 'users', type_='check')
    op.create_check_constraint(
        'ck_users_mobile_or_email_auth',
        'users',
        "((auth_type = 'email_auth') OR (mobile_number IS NOT NULL))"
    )
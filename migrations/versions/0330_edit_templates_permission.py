"""

Revision ID: 0330_edit_templates_permission
Revises: 0329_notification_status
Create Date: 2021-06-25 10:39:29.089237

"""

from alembic import op

revision = '0330_edit_templates_permission'
down_revision = '0329_notification_status'


def upgrade():
    # adding a value to an enum must be done outside of a transaction, hence autocommit_block
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE permission_types ADD VALUE 'edit_templates'")


def downgrade():
    # there's no ALTER TYPE ... DROP VALUE, so we've got to do this whole dance
    op.execute("ALTER TYPE permission_types RENAME TO permission_types_old")
    # old values
    op.execute("""
        CREATE TYPE permission_types AS ENUM(
            'manage_users', 'manage_templates', 'manage_settings', 'send_texts', 'send_emails', 'send_letters', 'manage_api_keys', 'platform_admin', 'view_activity'
        )
    """)
    op.execute("ALTER TABLE permissions ALTER COLUMN permission TYPE permission_types USING permission::text::permission_types")
    op.execute("DROP TYPE permission_types_old")

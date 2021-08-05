"""

Revision ID: 0320_remove_smtp
Revises: 0319_warn_daily_limits
Create Date: 2021-04-16 13:37:42

"""
from alembic import op

revision = "0320_remove_smtp"
down_revision = "0319_warn_daily_limits"


def upgrade():
    # Coming from migration 0305l_smtp_template
    template_id = "3a4cab41-c47d-4d49-96ba-f4c4fa91d44b"

    op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
    op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
    op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

    op.drop_column("services", "smtp_user")
    op.drop_column("services_history", "smtp_user")


def downgrade():
    pass

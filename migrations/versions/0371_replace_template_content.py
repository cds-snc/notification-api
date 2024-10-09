"""
Revision ID: 0371_replace_template_content
Revises: 0370_notification_callback_url
Create Date: 2024-10-08 20:35:38
"""
from alembic import op

revision = '0371_replace_template_content'
down_revision = '0370_notification_callback_url'

def upgrade():
    op.execute("""
        UPDATE templates
        SET content = REPLACE(content, 'https://notification.alpha.canada.ca', '')
    """)

    op.execute("""
        UPDATE templates_history
        SET content = REPLACE(content, 'https://notification.alpha.canada.ca', '')
    """)


def downgrade():
    # No-op for downgrade, since this change is not reversible
    pass
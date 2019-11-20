"""

Revision ID: 0305e_account_change_type
Revises: 0305d_block_users
Create Date: 2019-11-15 16:07:22.019759

"""
from flask import current_app
from alembic import op
import sqlalchemy as sa


revision = '0305e_account_change_type'
down_revision = '0305d_block_users'

templates = [
    {
        'id': '5b39e16a-9ff8-487c-9bfb-9e06bdb70f36',
        'name': 'Account update',
        'type': 'email',
        'subject': 'Notification user account information changed',
        'content_lines': [
            'Your user account information was changed on ((base_url)). ',
            '',
            'Updated information: ((change_type))',
            '',
            'If you did not make this change, contact us immediately using the following link:',
            '',
            '((contact_us_url))',
        ],
    },
]


def upgrade():
    insert = """
        INSERT INTO {} (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', current_timestamp, '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    for template in templates:
        for table_name in 'templates', 'templates_history':
            op.execute(
                insert.format(
                    table_name,
                    template['id'],
                    template['name'],
                    template['type'],
                    '\n'.join(template['content_lines']),
                    current_app.config['NOTIFY_SERVICE_ID'],
                    template.get('subject'),
                    current_app.config['NOTIFY_USER_ID'],
                    'normal'
                )
            )

        op.execute(
            """
            INSERT INTO template_redacted
            (
                template_id,
                redact_personalisation,
                updated_at,
                updated_by_id
            ) VALUES ( '{}', false, current_timestamp, '{}' )
            """.format(template['id'], current_app.config['NOTIFY_USER_ID'])
        )


def downgrade():
    for template in templates:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template['id']))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template['id']))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template['id']))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template['id']))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template['id']))

"""

Revision ID: 0300b_support_email_templates
Revises: 0300a_merge_heads
Create Date: 2019-07-29 17:18:00.0

"""
from alembic import op
from flask import current_app


revision = '0300b_support_email_templates'
down_revision = '0300a_merge_heads'


templates = [
    {
        'id': '8ea9b7a0-a824-4dd3-a4c3-1f508ed20a69',
        'name': 'Support - Contact Us',
        'type': 'email',
        'subject': 'Contact Us Form',
        'content_lines': [
            'User: ((user)) sent the following message:',
            '',
            '((message))',
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

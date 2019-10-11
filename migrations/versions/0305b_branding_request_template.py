"""

Revision ID: 0305b_branding_request_template
Revises: 0305a_merge
Create Date: 2019-07-30 09:26:00

"""
from alembic import op
from flask import current_app


revision = '0305b_branding_request_template'
down_revision = '0305a_merge'


templates = [
    {
        'id': '7d423d9e-e94e-4118-879d-d52f383206ae',
        'name': 'Support - Branding Request',
        'type': 'email',
        'subject': 'Branding Change Request for Service: ((service_name))',
        'content_lines': [
            'A new logo has been uploaded by ((email)) for the following service: ',
            '',
            'Service id: ((serviceID))',
            'Service name: ((service_name))',
            '',
            'Logo filename: ((filename))',
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

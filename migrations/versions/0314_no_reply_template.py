"""

Revision ID: 0314_no_reply_template
Revises: 0313_disable_pinpoint_provider
Create Date: 2021-02-09 13:37:42

"""
from alembic import op
from flask import current_app


revision = '0314_no_reply_template'
down_revision = '0313_disable_pinpoint_provider'


templates = [
    {
        'id': current_app.config['NO_REPLY_TEMPLATE_ID'],
        'name': 'No Reply',
        'type': 'email',
        'subject': 'Message not delivered | Message non livré',
        'content_lines': [
            "Your message was not delivered.",
            "",
            "The email address ((sending_email_address)) is not able to receive messages since this feature has not been set by the sender.",
            "",
            "___",
            "",
            "Votre message n’a pas été livré.",
            "",
            "L’adresse courriel ((sending_email_address)) ne peut pas recevoir de messages car cette fonction n’a pas été définie par l’expéditeur.",
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

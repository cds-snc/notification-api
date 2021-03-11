"""

Revision ID: 0319_create_complaint_template
Revises: 0318_remove_custom_email_from
Create Date: 2021-03-11 11:15:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

from app.models import EMAIL_TYPE, NORMAL

revision = '0319_create_complaint_template'
down_revision = '0318_remove_custom_email_from'

user_id = current_app.config['NOTIFY_USER_ID']
service_id = current_app.config['NOTIFY_SERVICE_ID']
complaint_template_id = current_app.config['EMAIL_COMPLAINT_TEMPLATE_ID']
complaint_template_name = 'received email complaint'
complaint_template_subject = 'received email complaint for ((notification_id))'


def upgrade():
    content = """An email has been marked as spam. Here is the complaint info: 


    \t notification_id: ((notification_id))

    \t service_name: ((service_name))

    \t template_name: ((template_name))


    """
    template_history_insert = f"""INSERT INTO templates_history (id, name, template_type, created_at,
                                                                content, archived, service_id, hidden,
                                                                subject, created_by_id, process_type, version)
                                 VALUES ('{complaint_template_id}', '{complaint_template_name}',
                                 '{EMAIL_TYPE}', '{datetime.utcnow()}', '{content}', False, '{service_id}', '{False}',
                                 '{complaint_template_subject}', '{user_id}', '{NORMAL}', 1)
                              """
    template_insert = f"""INSERT INTO templates (id, name, template_type, created_at,
                                                                content, archived, service_id, hidden,
                                                                subject, created_by_id, process_type, version)
                                 VALUES ('{complaint_template_id}', '{complaint_template_name}',
                                 '{EMAIL_TYPE}', '{datetime.utcnow()}', '{content}', False, '{service_id}', '{False}',
                                 '{complaint_template_subject}', '{user_id}', '{NORMAL}', 1)
                              """

    op.get_bind()
    op.execute(template_history_insert)
    op.execute(template_insert)

    # If you are copying this migration, please remember about an insert to TemplateRedacted,
    # which was not originally included here either by mistake or because it was before TemplateRedacted existed
    op.execute(
        f"""
            INSERT INTO template_redacted (template_id, redact_personalisation, updated_at, updated_by_id)
            VALUES ('{complaint_template_id}', '{False}', '{datetime.utcnow()}', '{user_id}')
            ;
        """
    )


def downgrade():
    op.execute(f"delete from notifications where template_id = '{complaint_template_id}'")
    op.execute(f"delete from jobs where template_id = '{complaint_template_id}'")
    op.execute(f"delete from template_redacted where template_id = '{complaint_template_id}'")
    op.execute(f"delete from templates_history where id = '{complaint_template_id}'")
    op.execute(f"delete from templates where id = '{complaint_template_id}'")

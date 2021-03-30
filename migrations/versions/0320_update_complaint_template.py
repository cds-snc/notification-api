"""

Revision ID: 0320_update_complaint_template
Revises: 0319_create_complaint_template
Create Date: 2021-03-29 11:05:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

from app.models import EMAIL_TYPE, NORMAL

revision = '0320_update_complaint_template'
down_revision = '0319_create_complaint_template'

complaint_template_id = current_app.config['EMAIL_COMPLAINT_TEMPLATE_ID']


def upgrade():
    tables = ['templates_history', 'templates']
    content = """An email has been marked as spam. Here is the complaint info:
                \n\t notification_id: ((notification_id))
                \n\t service_name: ((service_name))
                \n\t template_name: ((template_name))
                \n\t complaint_id: ((complaint_id))
                \n\t complaint_type: ((complaint_type))
                \n\t complaint_date: ((complaint_date))
                \n
            """

    op.get_bind()

    for table in tables:
        op.execute(f"""
            UPDATE {table}
            SET content = '{content}'
            WHERE id = '{complaint_template_id}'
        """)


def downgrade():
    pass

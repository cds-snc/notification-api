"""

Revision ID: 0321_update_complaint_template
Revises: 0320_update_complaint_template
Create Date: 2021-03-30 13:30:00

"""

from alembic import op
from flask import current_app


revision = '0321_update_complaint_template'
down_revision = '0320_update_complaint_template'

complaint_template_id = current_app.config['EMAIL_COMPLAINT_TEMPLATE_ID']


def upgrade():
    tables = ['templates_history', 'templates']
    content = """An email has been marked as spam. Here is the complaint info:\n
                * notification_id: ((notification_id))\n
                * service_name: ((service_name))\n
                * template_name: ((template_name))\n
                * complaint_id: ((complaint_id))\n
                * complaint_type: ((complaint_type))\n
                * complaint_date: ((complaint_date))\n
            """

    op.get_bind()

    for table in tables:
        op.execute(f"""
            UPDATE {table}
            SET content = '{content}'
            WHERE id = '{complaint_template_id}'
        """)  # nosec


def downgrade():
    pass

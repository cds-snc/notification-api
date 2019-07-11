"""

Revision ID: 0298c_replace_name_in_history
Revises: 0298b_replace_name_in_templates
Create Date: 2019-07-09 08:49:20.630174

"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = '0298c_replace_name_in_history'
down_revision = '0298b_replace_name_in_templates'

def upgrade():
    op.execute(f"""
        UPDATE 
          templates_history
        SET 
          name = REPLACE(name,'Notify','Notification'),
          subject = REPLACE(subject,'GOV.UK Notify','Notification'),
          content = REPLACE(content,'GOV.UK Notify','Notification')
    """)

    # For GOV.UK having different period characters
    op.execute(f"""
        UPDATE 
          templates_history
        SET 
          name = REPLACE(name,'GOV.UK',''),
          subject = REPLACE(subject,'GOV.​UK Notify','Notification'), 
          content = REPLACE(content,'Notify','Notification')
    """)

    op.execute(f"""
        UPDATE 
          templates_history
        SET 
          name = REPLACE(name,'GOV.UK',''),
          content = REPLACE(content,'https://www.gov.uk/notify','https://notification.alpha.canada.ca')
    """)

    op.execute(f"""
        UPDATE 
          templates_history
        SET 
          content = REPLACE(content,'GOV.​UK','')
    """)


def downgrade():
  op.execute(f"""
        UPDATE 
          templates_history
        SET 
          name = REPLACE(name,'Notification','Notify'),
          subject = REPLACE(subject,'Notification','GOV.UK Notify')
    """)

  op.execute(f"""
        UPDATE 
          templates_history
        SET 
          content = REPLACE(content,'https://notification.alpha.canada.ca','https://www.gov.uk/notify')
    """)

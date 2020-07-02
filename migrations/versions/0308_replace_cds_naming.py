"""

Revision ID: 0308_replace_cds_naming
Revises: 0307b_deactivate_mmg_loadtesting
Create Date: 2020-07-02 11:19:20.600074

"""
from alembic import op

revision = '0308_replace_cds_naming'
down_revision = '0307b_deactivate_mmg_loadtesting'


def upgrade():
    op.execute("""
        UPDATE 
            services 
        SET 
            name = 'VA Notify', 
            email_from = 'va-notify'
        WHERE 
            id='d6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)

    op.execute("""
        UPDATE 
            users
        SET 
            email_address = 'va-notify-user@public.govdelivery.com',
            mobile_number = '+16173263357'
        WHERE 
            id='6af522d0-2915-4e52-83a3-3690455a5fe6'
    """)

    op.execute(f"""
        UPDATE 
          templates
        SET 
          name = REPLACE(name,'Notification','VA Notify'),
          subject = REPLACE(subject,'Notification','VA Notify'),
          content = REPLACE(content,'Notification','VA Notify')
        WHERE
          service_id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)

    # For GOV.UK having different period characters
    op.execute(f"""
        UPDATE 
          templates
        SET 
          subject = REPLACE(subject,'Notification','VA Notify'), 
          content = REPLACE(content,'Notification','VA Notify')
        WHERE
          service_id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)


def downgrade():
    op.execute("""
        UPDATE 
            services 
        SET 
            name = 'Notification', 
            email_from = 'notification'
        WHERE 
            id='d6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)

    op.execute("""
        UPDATE 
            users
        SET 
            email_address = 'notify-service-user@notification.alpha.canada.ca',
            mobile_number = '+16135555555'
        WHERE 
            id='6af522d0-2915-4e52-83a3-3690455a5fe6'
    """)

    op.execute(f"""
        UPDATE 
          templates
        SET 
          name = REPLACE(name,'VA Notify','Notification'),
          subject = REPLACE(subject,'VA Notify','Notification'),
          content = REPLACE(content,'VA Notify','Notification')
        WHERE
          service_id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)

    # For GOV.UK having different period characters
    op.execute(f"""
        UPDATE 
          templates
        SET 
          subject = REPLACE(subject,'VA Notify','Notification'), 
          content = REPLACE(content,'VA Notify','Notification')
        WHERE
          service_id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)


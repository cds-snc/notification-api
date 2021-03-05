"""

Revision ID: 0318_remove_custom_email_from
Revises: 0317_provider_load_balancing
Create Date: 2021-03-05 07:51:12.100077

"""
from alembic import op

revision = '0318_remove_custom_email_from'
down_revision = '0317_provider_load_balancing'


def upgrade():
    op.execute("""
        UPDATE 
            services 
        SET 
            email_from = NULL
        WHERE 
            id='d6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)


def downgrade():
    op.execute("""
        UPDATE 
            services 
        SET 
            email_from = 'va-notify'
        WHERE 
            id='d6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    """)

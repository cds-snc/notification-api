"""

Revision ID: 0300c_remove_email_branding
Revises: 0300b_support_email_templates
Create Date: 2019-07-29 16:18:27.467361

"""

# revision identifiers, used by Alembic.
revision = '0300c_remove_email_branding'
down_revision = '0300b_support_email_templates'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # UK Visas & Immigration
    op.execute(f"""
        DELETE FROM 
          email_branding
        WHERE 
          id = '9d25d02d-2915-4e98-874b-974e123e8536'
    """)

    # data gov.uk
    op.execute(f"""
        DELETE FROM 
          email_branding
        WHERE 
          id = '123496d4-44cb-4324-8e0a-4187101f4bdc'
    """)

    # tfl
    op.execute(f"""
        DELETE FROM 
          email_branding
        WHERE 
          id = '1d70f564-919b-4c68-8bdf-b8520d92516e'
    """)

    # een
    op.execute(f"""
        DELETE FROM 
          email_branding
        WHERE 
          id = '89ce468b-fb29-4d5d-bd3f-d468fb6f7c36'
    """)


def downgrade():
    pass
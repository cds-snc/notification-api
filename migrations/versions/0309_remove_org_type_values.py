"""

Revision ID: 0309_remove_org_type_values
Revises: 0308_replace_cds_naming
Create Date: 2020-07-08 12:02:09.093272

"""
from alembic import op

revision = '0309_remove_org_type_values'
down_revision = '0308_replace_cds_naming'


def upgrade():
    op.execute("DELETE FROM organisation_types WHERE NOT name='other'")

def downgrade():
    op.execute("""
        INSERT INTO organisation_types (
            name, is_crown, annual_free_sms_fragment_limit
        )
        VALUES
            ('central', None, 250000),
            ('local', False, 25000),
            ('nhs', None, 25000),
            ('nhs_central', True, 250000),
            ('nhs_local', False, 25000),
            ('emergency_service', False, 25000),
            ('school_or_college', False, 25000)
    """)
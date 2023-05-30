"""

Revision ID: 0431_add_pt_organisation_type
Revises: 0430_add_contact_form_email
Create Date: 2023-05-30 00:00:00

"""

from alembic import op

revision = "0431_add_pt_organisation_type"
down_revision = "0430_add_contact_form_email"


def upgrade():
    op.execute(
        f"""
        INSERT INTO organisation_types (name, is_crown, annual_free_sms_fragment_limit) 
        VALUES ('province_or_territory', null, 250000)
    """
    )


def downgrade():
    op.execute("DELETE FROM organisation_types WHERE name = 'province_or_territory'")

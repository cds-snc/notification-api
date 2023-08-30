"""

Revision ID: 0361_remove_letter_branding
Revises: 0360_add_edipi_identifier_type
Create Date: 2023-08-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0361_remove_letter_branding'
down_revision = '0360_add_edipi_identifier_type'

# old_id_types = sa.Enum('VAPROFILEID', 'PID', 'ICN', 'BIRLSID', name='id_types')
# new_id_types = sa.Enum('VAPROFILEID', 'PID', 'ICN', 'BIRLSID', 'EDIPI', name='id_types')


def upgrade():
    # drop references in tables
    op.execute("""ALTER TABLE ONLY organisation DROP CONSTRAINT fk_organisation_letter_branding_id""")
    op.execute("""ALTER TABLE ONLY organisation DROP COLUMN letter_branding_id""")
    
    op.execute("""ALTER TABLE ONLY service_letter_branding DROP CONSTRAINT service_letter_branding_letter_branding_id_fkey""")
    op.execute("""ALTER TABLE ONLY service_letter_branding DROP COLUMN letter_branding_id""")
    
    # drop unused tables
    op.drop_table('service_letter_branding')
    op.drop_table('letter_branding')


def downgrade():
    # restore 'letter_branding' table
    op.execute("""CREATE TABLE letter_branding (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    filename character varying(255) NOT NULL)""")

    op.execute("""ALTER TABLE ONLY letter_branding
    ADD CONSTRAINT letter_branding_filename_key UNIQUE (filename)""")

    op.execute("""ALTER TABLE ONLY letter_branding
    ADD CONSTRAINT letter_branding_name_key UNIQUE (name)""")

    op.execute("""ALTER TABLE ONLY letter_branding
    ADD CONSTRAINT letter_branding_pkey PRIMARY KEY (id)""")

    # restore 'service_letter_branding' table
    op.execute("""CREATE TABLE service_letter_branding (
    service_id uuid NOT NULL,
    letter_branding_id uuid NOT NULL)""")

    op.execute("""ALTER TABLE ONLY service_letter_branding
    ADD CONSTRAINT service_letter_branding_pkey PRIMARY KEY (service_id)""")

    op.execute("""ALTER TABLE ONLY service_letter_branding
    ADD CONSTRAINT service_letter_branding_letter_branding_id_fkey FOREIGN KEY (letter_branding_id) REFERENCES letter_branding(id)""")

    op.execute("""ALTER TABLE ONLY service_letter_branding
    ADD CONSTRAINT service_letter_branding_service_id_fkey FOREIGN KEY (service_id) REFERENCES services(id)""")

    # restore foreign key in 'organization'
    op.add_column('organisation', sa.Column('letter_branding_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_organisation_letter_branding_id', 'organisation', 'letter_branding', ['letter_branding_id'], ['id'])


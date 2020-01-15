"""

Revision ID: 0305k_user_info_column
Revises: 0305j_add_branding_option 
Create Date: 2020-01-05 11:24:58.773824

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0305k_add_branding_option'
down_revision = '0305j_add_branding_option'


def upgrade():
     op.add_column('users', sa.Column('additional_information', postgresql.JSONB(), nullable=True))


def downgrade():
     op.drop_column('users', 'additional_information')

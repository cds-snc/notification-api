"""
Revision ID: 0346_create_va_profile_functions
Revises: 0345_alter_VAProfileLocalCache
Create Date: 2022-04-29 21:38:57.302588
"""

from alembic import op
import sqlalchemy as sa
from alembic_utils.pg_function import PGFunction
from sqlalchemy import text as sql_text
from sqlalchemy.dialects import postgresql

revision = '0346_create_va_profile_functions'
down_revision = '0345_alter_VAProfileLocalCache'


def upgrade():
    public_va_profile_opt_in = PGFunction(
        schema="public",
        signature="va_profile_opt_in(_mpi_icn varchar(29), _va_profile_id integer, _communication_item_id integer, _communication_channel_name varchar(255))",
        definition='RETURNS void\nLANGUAGE sql AS $$\n    INSERT INTO va_profile_local_cache (mpi_icn, va_profile_id, communication_item_id, communication_channel_name)\n    VALUES (_mpi_icn, _va_profile_id, _communication_item_id, _communication_channel_name)\n    ON CONFLICT DO NOTHING;\n$$'
    )
    op.create_entity(public_va_profile_opt_in)

    public_va_profile_opt_out = PGFunction(
        schema="public",
        signature="va_profile_opt_out(_va_profile_id integer, _communication_item_id integer, _communication_channel_name varchar(255))",
        definition='RETURNS void\nLANGUAGE sql AS $$\n    DELETE FROM va_profile_local_cache\n    WHERE va_profile_id = _va_profile_id AND communication_item_id = _communication_item_id AND communication_channel_name = _communication_channel_name;\n$$'
    )
    op.create_entity(public_va_profile_opt_out)


def downgrade():
    public_va_profile_opt_out = PGFunction(
        schema="public",
        signature="va_profile_opt_out(_va_profile_id integer, _communication_item_id integer, _communication_channel_name varchar(255))",
        definition='RETURNS void\nLANGUAGE sql AS $$\n    DELETE FROM va_profile_local_cache\n    WHERE va_profile_id = _va_profile_id AND communication_item_id = _communication_item_id AND communication_channel_name = _communication_channel_name;\n$$'
    )
    op.drop_entity(public_va_profile_opt_out)

    public_va_profile_opt_in = PGFunction(
        schema="public",
        signature="va_profile_opt_in(_mpi_icn varchar(29), _va_profile_id integer, _communication_item_id integer, _communication_channel_name varchar(255))",
        definition='RETURNS void\nLANGUAGE sql AS $$\n    INSERT INTO va_profile_local_cache (mpi_icn, va_profile_id, communication_item_id, communication_channel_name)\n    VALUES (_mpi_icn, _va_profile_id, _communication_item_id, _communication_channel_name)\n    ON CONFLICT DO NOTHING;\n$$'
    )
    op.drop_entity(public_va_profile_opt_in)

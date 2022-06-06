"""
Revision ID: 0347_modify_table_and_function
Revises: 0346_create_va_profile_functions
Create Date: 2022-05-26 23:33:03.853609
"""

import sqlalchemy as sa
from alembic import op
from alembic_utils.pg_function import PGFunction

revision = '0347_modify_table_and_function'
down_revision = '0346_create_va_profile_functions'


def upgrade():
    public_va_profile_opt_in = PGFunction(
        schema="public",
        signature="va_profile_opt_in(_mpi_icn character varying, _va_profile_id integer, _communication_item_id integer, _communication_channel_name character varying)",
        definition='returns void\n LANGUAGE sql\nAS $function$\n    INSERT INTO va_profile_local_cache (mpi_icn, va_profile_id, communication_item_id, communication_channel_name)\n    VALUES (_mpi_icn, _va_profile_id, _communication_item_id, _communication_channel_name)\n    ON CONFLICT DO NOTHING;\n$function$'
    )
    op.drop_entity(public_va_profile_opt_in)

    public_va_profile_opt_out = PGFunction(
        schema="public",
        signature="va_profile_opt_out(_va_profile_id integer, _communication_item_id integer, _communication_channel_name character varying)",
        definition='returns void\n LANGUAGE sql\nAS $function$\n    DELETE FROM va_profile_local_cache\n    WHERE va_profile_id = _va_profile_id AND communication_item_id = _communication_item_id AND communication_channel_name = _communication_channel_name;\n$function$'
    )
    op.drop_entity(public_va_profile_opt_out)

    op.add_column('va_profile_local_cache', sa.Column('allowed', sa.Boolean(), nullable=False))
    op.add_column('va_profile_local_cache', sa.Column('communication_channel_id', sa.Integer(), nullable=False))
    op.add_column('va_profile_local_cache', sa.Column('source_datetime', sa.DateTime(), nullable=True))
    op.create_unique_constraint('uix_veteran_id', 'va_profile_local_cache', ['va_profile_id', 'communication_item_id', 'communication_channel_id'])
    op.drop_column('va_profile_local_cache', 'communication_channel_name')
    op.drop_column('va_profile_local_cache', 'mpi_icn')

    public_va_profile_opt_in_out = PGFunction(
        schema="public",
        signature="va_profile_opt_in_out(_va_profile_id integer, _communication_item_id integer, _communication_channel_id integer, _allowed Boolean, _source_datetime timestamp)",
        definition='RETURNS boolean\nLANGUAGE sql AS $$\nINSERT INTO va_profile_local_cache(va_profile_id, communication_item_id, communication_channel_id, source_datetime, allowed)\n    VALUES(_va_profile_id, _communication_item_id, _communication_channel_id, _source_datetime, _allowed)\n\tON CONFLICT ON CONSTRAINT uix_veteran_id DO UPDATE\n    SET allowed = _allowed, source_datetime = _source_datetime\n    WHERE _source_datetime > va_profile_local_cache.source_datetime\n        AND va_profile_local_cache.va_profile_id = _va_profile_id\n        AND va_profile_local_cache.communication_item_id = _communication_item_id\n        AND va_profile_local_cache.communication_channel_id = _communication_channel_id\n    RETURNING true\n$$'
    )
    op.create_entity(public_va_profile_opt_in_out)


def downgrade():
    public_va_profile_opt_in_out = PGFunction(
        schema="public",
        signature="va_profile_opt_in_out(_va_profile_id integer, _communication_item_id integer, _communication_channel_id integer, _allowed Boolean, _source_datetime timestamp)",
        definition='RETURNS boolean\nLANGUAGE sql AS $$\nINSERT INTO va_profile_local_cache(va_profile_id, communication_item_id, communication_channel_id, source_datetime, allowed)\n    VALUES(_va_profile_id, _communication_item_id, _communication_channel_id, _source_datetime, _allowed)\n\tON CONFLICT ON CONSTRAINT uix_veteran_id DO UPDATE\n    SET allowed = _allowed, source_datetime = _source_datetime\n    WHERE _source_datetime > va_profile_local_cache.source_datetime\n        AND va_profile_local_cache.va_profile_id = _va_profile_id\n        AND va_profile_local_cache.communication_item_id = _communication_item_id\n        AND va_profile_local_cache.communication_channel_id = _communication_channel_id\n    RETURNING true\n$$'
    )
    op.drop_entity(public_va_profile_opt_in_out)

    op.add_column('va_profile_local_cache', sa.Column('mpi_icn', sa.VARCHAR(length=29), autoincrement=False, nullable=False))
    op.add_column('va_profile_local_cache', sa.Column('communication_channel_name', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
    op.drop_constraint('uix_veteran_id', 'va_profile_local_cache', type_='unique')
    op.drop_column('va_profile_local_cache', 'source_datetime')
    op.drop_column('va_profile_local_cache', 'communication_channel_id')
    op.drop_column('va_profile_local_cache', 'allowed')

    public_va_profile_opt_out = PGFunction(
        schema="public",
        signature="va_profile_opt_out(_va_profile_id integer, _communication_item_id integer, _communication_channel_name character varying)",
        definition='returns void\n LANGUAGE sql\nAS $function$\n    DELETE FROM va_profile_local_cache\n    WHERE va_profile_id = _va_profile_id AND communication_item_id = _communication_item_id AND communication_channel_name = _communication_channel_name;\n$function$'
    )
    op.create_entity(public_va_profile_opt_out)

    public_va_profile_opt_in = PGFunction(
        schema="public",
        signature="va_profile_opt_in(_mpi_icn character varying, _va_profile_id integer, _communication_item_id integer, _communication_channel_name character varying)",
        definition='returns void\n LANGUAGE sql\nAS $function$\n    INSERT INTO va_profile_local_cache (mpi_icn, va_profile_id, communication_item_id, communication_channel_name)\n    VALUES (_mpi_icn, _va_profile_id, _communication_item_id, _communication_channel_name)\n    ON CONFLICT DO NOTHING;\n$function$'
    )
    op.create_entity(public_va_profile_opt_in)

from __future__ import with_statement
from alembic import context
from alembic_utils.pg_function import PGFunction
from alembic_utils.replaceable_entity import register_entities
from sqlalchemy import engine_from_config, pool
from logging.config import fileConfig

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from flask import current_app
config.set_main_option('sqlalchemy.url', current_app.config.get('SQLALCHEMY_DATABASE_URI'))
target_metadata = current_app.extensions['migrate'].db.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


#######################################################################
# Define and register the stored procedures for VA Profile integration.
#######################################################################

va_profile_opt_in_out = PGFunction(
  schema="public",
  signature="va_profile_opt_in_out(_va_profile_id integer, _communication_item_id integer, _communication_channel_id integer, _allowed Boolean, _source_datetime timestamp)",
  definition="""\
RETURNS boolean AS
$$
DECLARE number_of_changed_records Int;
BEGIN
INSERT INTO va_profile_local_cache(va_profile_id, communication_item_id, communication_channel_id, source_datetime, allowed)
    VALUES(_va_profile_id, _communication_item_id, _communication_channel_id, _source_datetime, _allowed)
	ON CONFLICT ON CONSTRAINT uix_veteran_id DO UPDATE
    SET allowed = _allowed, source_datetime = _source_datetime
    WHERE _source_datetime > va_profile_local_cache.source_datetime
        AND va_profile_local_cache.va_profile_id = _va_profile_id
        AND va_profile_local_cache.communication_item_id = _communication_item_id
        AND va_profile_local_cache.communication_channel_id = _communication_channel_id;
GET DIAGNOSTICS number_of_changed_records = ROW_COUNT; 
RETURN number_of_changed_records > 0; 
END
$$
LANGUAGE plpgsql
"""
)

#######################################################################
# Define and register the stored procedures for VA Profile integration.
#######################################################################

va_profile_remove_old_opt_outs = PGFunction(
  schema="public",
  signature="va_profile_remove_old_opt_outs()",
  definition="""\
RETURNS void AS
  $$
DELETE
FROM va_profile_local_cache
WHERE allowed = False 
AND age(NOW(), source_datetime) > INTERVAL '24 hours';
$$
LANGUAGE sql
"""
)

register_entities([va_profile_opt_in_out, va_profile_remove_old_opt_outs])

#######################################################################

def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url)

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    engine = engine_from_config(
                config.get_section(config.config_ini_section),
                prefix='sqlalchemy.',
                poolclass=pool.NullPool)

    connection = engine.connect()
    context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True
                )

    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.close()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()


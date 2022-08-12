import logging
import os
import psycopg2
import sys

# Set globals
REMOVE_OPTED_OUT_RECORDS_QUERY = """SELECT va_profile_remove_old_opt_outs();"""
SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI")
logger = logging.getLogger('va_profile_remove_old_opt_outs')
logger.setLevel(logging.INFO)

# Verify environment is setup correctly
if SQLALCHEMY_DATABASE_URI is None:
    logger.error("The database URI is not set.")
    sys.exit("Couldn't connect to the database.")
else:
    logger.info('Execution environment prepared...')


def va_profile_remove_old_opt_outs_handler(event=None, context=None, worker_id=None):
    """
    This function deletes any va_profile cache records that
    are opted out and greater than 24 hours old.
    """
    connection = None

    # https://www.psycopg.org/docs/module.html#exceptions
    try:
        logger.info('Connecting to database...')
        connection = psycopg2.connect(SQLALCHEMY_DATABASE_URI + ('' if worker_id is None else f"_{worker_id}"))

        with connection.cursor() as c:
            logger.info('Executing database function...')
            c.execute(REMOVE_OPTED_OUT_RECORDS_QUERY)
            logger.info('Committing to database...')
            connection.commit()
            logger.info('Completed commit...')
    except psycopg2.Warning as e:
        logger.warning(e)
    except psycopg2.Error as e:
        logger.exception(e)
        # https://www.postgresql.org/docs/11/errcodes-appendix.html
        logger.error(e.pgcode)
    except Exception as e:
        logger.exception(e)
    finally:
        if connection:
            connection.close()
            logger.info('Connection closed...')

import boto3
import logging
import os
import psycopg2
import sys

logger = logging.getLogger('va_profile_remove_old_opt_outs')
logger.setLevel(logging.DEBUG)

REMOVE_OPTED_OUT_RECORDS_QUERY = """SELECT va_profile_remove_old_opt_outs();"""

# Get the database URI.  The environment variable SQLALCHEMY_DATABASE_URI is
# set during unit testing.
sqlalchemy_database_uri = os.getenv('SQLALCHEMY_DATABASE_URI')

if sqlalchemy_database_uri is None:
    # This should be an AWS deployment environment.  SQLALCHEMY_DATABASE_URI
    # is not set in that case.

    database_uri_path = os.getenv('DATABASE_URI_PATH')
    if database_uri_path is None:
        # Without this value, this code cannot know the path to the required
        # SSM Parameter Store resource.
        sys.exit('DATABASE_URI_PATH is not set.  Check the Lambda console.')

    logger.debug('Getting the database URI from SSM Parameter Store . . .')
    ssm_client = boto3.client('ssm')
    ssm_response: dict = ssm_client.get_parameter(Name=database_uri_path, WithDecryption=True)
    logger.debug('. . . Retrieved the database URI from SSM Parameter Store.')
    sqlalchemy_database_uri = ssm_response.get('Parameter', {}).get('Value')

if sqlalchemy_database_uri is None:
    sys.exit("Can't get the database URI.")


def va_profile_remove_old_opt_outs_handler(
    event=None,
    context=None,
    worker_id=None,
):
    """
    This function deletes any va_profile cache records that
    are opted out and greater than 24 hours old.
    """

    logger.info('Removing old opt-outs . . .')
    connection = None

    # https://www.psycopg.org/docs/module.html#exceptions
    try:
        logger.info('Connecting to the database...')
        connection = psycopg2.connect(sqlalchemy_database_uri + ('' if worker_id is None else f'_{worker_id}'))
        logger.info('. . . Connected to the database.')

        with connection.cursor() as c:
            logger.info('Executing the stored function')
            c.execute(REMOVE_OPTED_OUT_RECORDS_QUERY)
            logger.info('Committing the database transaction.')
            connection.commit()
    except psycopg2.Warning as e:
        logger.warning(e)
    except psycopg2.Error as e:
        logger.exception(e)
        # https://www.postgresql.org/docs/11/errcodes-appendix.html
        logger.error(e.pgcode)
    except Exception as e:
        logger.exception(e)
    finally:
        if connection is not None:
            connection.close()
            logger.info('Connection closed.')

    logger.info('. . . Finished removing old opt-outs.')

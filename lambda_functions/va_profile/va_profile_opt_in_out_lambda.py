# Tutorial: Configuring a Lambda function to access Amazon RDS in an Amazon VPC
#   https://docs.aws.amazon.com/lambda/latest/dg/services-rds-tutorial.html
# https://www.psycopg.org/docs/usage.html

import logging
import os
import psycopg2
import sys

OPT_IN_OUT_QUERY = """SELECT va_profile_opt_in_out(%s, %s, %s, %s, %s);"""
NOTIFICATION_API_DB_URI = os.getenv("notification_api_db_uri")

if NOTIFICATION_API_DB_URI is None:
    logging.error("The database URI is not set.")
    sys.exit("Couldn't connect to the database.")


def make_connection():
    """
    Return a connection to the database, or return None.
    """

    connection = None

    # https://www.psycopg.org/docs/module.html#exceptions
    try:
        connection = psycopg2.connect(NOTIFICATION_API_DB_URI)
    except psycopg2.Warning as e:
        logging.warning(e)
    except psycopg2.Error as e:
        logging.exception(e)
        logging.error(e.pgcode)

    return connection


db_connection = None


def va_profile_opt_in_out_lambda_handler(event: dict, context) -> dict:
    """
    Use the event data to process veterans' opt-in/out requests as relayed by VA Profile.  The data fields
    are as specified in the "VA Profile Syncronization" document.  It looks like this:

        {
            txAuditId": "string",
            ...
            "bios": [
                {
                "txAuditId": "string",
                "sourceDate": "2022-03-07T19:37:59.320Z",
                "vaProfileId": 0,
                "communicationChannelId": 0,
                "communicationItemId": 0,
                "allowed": true,
                ...
                }
            ]
        }

    The lambda generally will be called by the Amazon API Gateway service.  Useful documentation:
        https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html
        https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html
        https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-concepts.html#gettingstarted-concepts-event
    """

    if "txAuditId" not in event or "bios" not in event or not isinstance(event["bios"], list):
        # A required top level attribute is missing from the request.
        logging.debug(event)
        return { "statusCode": 400 }

    response = { "statusCode": 200 }

    for record in event["bios"]:
        try:
            params = (                             # Stored function parameters:
                record["VaProfileId"],             #     _va_profile_id
                record["CommunicationItemId"],     #     _communication_item_id
                record["CommunicationChannelId"],  #     _communication_channel_name
                record["allowed"],                 #     _allowed
                record["sourceDate"],              #     _source_datetime
            )

            if db_connection is None or db_connection.status != 0:
                # Attempt to (re-)establish a database connection
                db_connection = make_connection()

            if db_connection is None:
                raise RuntimeError("No database connection.")

            # Execute the appropriate stored function.
            with connection.cursor() as c:
                c.execute(OPT_IN_OUT_QUERY, params)
        except KeyError as e:
            # Bad Request
            response["statusCode"] = 400
            logging.exception(e)

            # TODO - set PUT response value
        except Exception as e:
            # Internal Server Error.  Prefer to return 400 if multiple records raise exceptions.
            if response["statusCode"] != 400:
                response["statusCode"] = 500
            logging.exception(e)

            # TODO - set PUT response value

    if response["statusCode"] != 200:
        logging.debug(event)

    # TODO - PUT back to VA Profile

    return response

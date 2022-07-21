"""
Tutorial: Configuring a Lambda function to access Amazon RDS in an Amazon VPC
   https://docs.aws.amazon.com/lambda/latest/dg/services-rds-tutorial.html

Other useful documentation:
    https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-concepts.html#gettingstarted-concepts-event
    https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html
    https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html
    https://docs.aws.amazon.com/lambda/latest/dg/python-logging.html
    https://www.psycopg.org/docs/usage.html
    https://pyjwt.readthedocs.io/en/stable/usage.html
"""

import boto3
import jwt
import logging
import os
import psycopg2
import ssl
import sys
from cryptography.x509 import load_pem_x509_certificate
from http.client import HTTPSConnection
from json import dumps

logger = logging.getLogger("VAProfileOptInOut")
logger.setLevel(logging.DEBUG)

OPT_IN_OUT_QUERY = """SELECT va_profile_opt_in_out(%s, %s, %s, %s, %s);"""
NOTIFY_ENVIRONMENT = os.getenv("NOTIFY_ENVIRONMENT")
# TODO - Make this an SSM call.
SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI")
VA_PROFILE_DOMAIN = os.getenv("VA_PROFILE_DOMAIN")
VA_PROFILE_PATH_BASE = "/communication-hub/communication/v1/status/changelog/"
VA_PROFILE_PUBLIC_KEY = os.getenv("VA_PROFILE_PUBLIC_KEY")


# TODO - Make this an SSM call.
if SQLALCHEMY_DATABASE_URI is None:
    logger.error("SQLALCHEMY_DATABASE_URI is not set.")
    sys.exit("Couldn't connect to the database.")


if VA_PROFILE_PUBLIC_KEY is None:
    logger.error("VA_PROFILE_PUBLIC_KEY is not set.")
    sys.exit("Unable to verify JWTs in POST requests.")


try:
    # This is a public certificate in .pem format.  Use it to verify the signature
    # of the JWT contained in POST requests from VA Profile.
    va_profile_public_cert = load_pem_x509_certificate(VA_PROFILE_PUBLIC_KEY.encode()).public_key()
except ValueError as e:
    logger.exception(e)
    logger.debug("VA_PROFILE_PUBLIC_KEY =\n%s", VA_PROFILE_PUBLIC_KEY)
    sys.exit("Unable to verify JWTs in POST requests.")


# This is the VA root chain used to verify the certiicate VA Profile uses for 2-way TLS when
# this code makes a PUT request to a VA Profile endpoint.
va_root_pem = None
requested_va_root_pem = False


def get_va_root_pem() -> str:
    """
    Get the VA root certificate pem chain from AWS SSM Parameter Store.

    The execution role that imports the module is not the same execution role that executes
    the handler.  Call this function from within the handler to avoid a hard-to-identify
    permissions problem that results in the lambda call timing-out.
    """

    assert not requested_va_root_pem, "Don't call this function more than once."
    the_pem = None

    if NOTIFY_ENVIRONMENT is None:
        logger.error("NOTIFY_ENVIRONMENT is not set.  Unable to make PUT requests.")
    elif VA_PROFILE_DOMAIN is None:
        logger.error("Could not get the domain for VA Profile.  Unable to make PUT requests.")
    elif NOTIFY_ENVIRONMENT != "test":
        logger.debug("Getting the VA root pem from SSM . . .")
        ssm_client = boto3.client("ssm")

        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm.html?highlight=get_parameter#SSM.Client.get_parameter
        # TODO - "get_parameters" could be used to get the VA root pem and the db URI
        # in one call.
        response = ssm_client.get_parameter(
            Name=f"/{NOTIFY_ENVIRONMENT}/notification-api/va-profile/va-root-pem",
            WithDecryption=True
        )

        the_pem = response.get("Parameter", {}).get("Value")

        if the_pem is None:
            logger.error("Couldn't get the VA root chain.  Unable to make PUT requests.")
            logger.debug(response)
        else:
            logger.debug("Retrieved the VA root pem.")
    # Else: Do not make requests to AWS for unit tests.

    return the_pem


def make_connection(worker_id):
    """
    Return a connection to the database, or return None.

    https://www.psycopg.org/docs/module.html#psycopg2.connect
    https://www.psycopg.org/docs/module.html#exceptions
    """

    connection = None

    try:
        connection = psycopg2.connect(SQLALCHEMY_DATABASE_URI + ('' if worker_id is None else f"_{worker_id}"))
    except psycopg2.Warning as e:
        logger.warning(e)
    except psycopg2.Error as e:
        logger.exception(e)
        logger.error(e.pgcode)

    return connection


db_connection = None
ssl_context = None


def va_profile_opt_in_out_lambda_handler(event: dict, context, worker_id=None) -> dict:
    """
    Use the event data to process veterans' opt-in/out requests as relayed by VA Profile.  The event is as proxied by the
    API gateway:
        https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html#apigateway-example-event
    
    The event "body" fields are as specified in the "VA Profile Syncronization" document:

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

    When this function is called from a unit test, the database URI will differ slightly from the environment
    variable, SQLALCHEMY_DATABASE_URI.  The parameter worker_id is used to construct the modified name in the
    same manner as in the tests/conftest.py::notify_db fixture.
    """

    logger.debug(event)

    headers = event.get("headers", {})
    if not jwt_is_valid(headers.get("Authorization", headers.get("authorization", ''))):
        return { "statusCode": 401 }

    global db_connection, requested_va_root_pem, ssl_context, va_root_pem
    body = event["body"]

    if "txAuditId" not in body or "bios" not in body or not isinstance(body["bios"], list):
        return { "statusCode": 400, "body": "A required top level attribute is missing from the request body or has the wrong type." }

    response = { "statusCode": 200 }

    put_request_body = {
        "txAuditId": body["txAuditId"],
        "bios": [],
    }

    # Process the preference updates.
    for record in body["bios"]:
        put_record = {
            "vaProfileId": record.get("vaProfileId", "unknown"),
            "communicationChannelId": record.get("communicationChannelId", "unknown"),
            "communicationItemId": record.get("communicationItemId", "unknown"),
        }

        if record.get("txAuditId", '') != body["txAuditId"]:
            # Do not query the database in response to this record.
            put_record["status"] = "COMPLETED_FAILURE"
            put_record["info"] = "The record's txAuditId, {}, does not match the event's txAuditId, {}.".format(record.get('txAuditId', '<unknown>'), body["txAuditId"])
            put_request_body["bios"].append(put_record)
            continue

        if record.get("communicationItemId", -1) != 5:
            put_record["status"] = "COMPLETED_NOOP"
            put_request_body["bios"].append(put_record)
            continue

        try:
            params = (                             # Stored function parameters:
                record["vaProfileId"],             #     _va_profile_id
                record["communicationItemId"],     #     _communication_item_id
                record["communicationChannelId"],  #     _communication_channel_name
                record["allowed"],                 #     _allowed
                record["sourceDate"],              #     _source_datetime
            )

            if db_connection is None or db_connection.status != 0:
                # Attempt to (re-)establish a database connection
                db_connection = make_connection(worker_id)

            if db_connection is None:
                raise RuntimeError("No database connection.")

            # Execute the stored function.
            with db_connection.cursor() as c:
                # https://www.psycopg.org/docs/cursor.html#cursor.execute
                c.execute(OPT_IN_OUT_QUERY, params)
                put_record["status"] = "COMPLETED_SUCCESS" if c.fetchone()[0] else "COMPLETED_NOOP"
                db_connection.commit()
        except KeyError as e:
            # Bad Request.  Required attributes are missing.
            response["statusCode"] = 400
            put_record["status"] = "COMPLETED_FAILURE"
            logger.exception(e)
        except Exception as e:
            # Internal Server Error.  Prefer to return 400 if multiple records raise exceptions.
            if response["statusCode"] != 400:
                response["statusCode"] = 500
            put_record["status"] = "COMPLETED_FAILURE"
            logger.exception(e)
        finally:
            put_request_body["bios"].append(put_record)

    if not requested_va_root_pem:
        va_root_pem = get_va_root_pem()
        requested_va_root_pem = True

    if va_root_pem is not None and put_request_body["bios"]:
        try:
            if ssl_context is None:
                # Use the VA root .pem to authenticate VA Profile's server.
                ssl_context = ssl.create_default_context(cadata=va_root_pem)

            try:
                # Make a PUT request to VA Profile.
                https_connection = HTTPSConnection(VA_PROFILE_DOMAIN, context=ssl_context)

                https_connection.request(
                    "PUT",
                    VA_PROFILE_PATH_BASE + body["txAuditId"],
                    dumps(put_request_body),
                    { "Content-Type": "application/json" }
                )

                put_response = https_connection.response()

                if put_response.status != 200:
                    logger.info("VA Profile responded to our PUT request with HTTP status %d.", put_response.status)
                    logger.debug(put_response)
            except ConnectionError as e:
                logger.error("The PUT request to VA Profile failed.")
                logger.exception(e)
            finally:
                https_connection.close()
        except ssl.SSLError as e:
            logger.exception(e)

    return response


def jwt_is_valid(auth_header_value: str) -> bool:
    """
    VA Profile should have sent an asymmetrically signed JWT with their POST request.
    """

    if not auth_header_value:
        return False

    try:
        # The authorization header value should look like "Bearer alsdkjadsf09e8adsfadskj".
        bearer, token = auth_header_value.split()
    except ValueError as e:
        logger.exception(e)
        logger.debug(auth_header_value)
        return False

    if bearer.title() != "Bearer":
        logger.debug("Malformed Authorization header value: ", auth_header_value)
        return False

    options = {
        "require": ["exp", "iat"],
        "verify_exp": "verify_signature",
    }

    try:
        # This returns the claims as a dictionary, but we aren't using them.  Require the
        # Issued at Time (iat) claim to ensure the JWT varies with each request.  Otherwise,
        # an attacker could replay the static Bearer value.
        jwt.decode(token, va_profile_public_cert, algorithms=["RS256"], options=options)
        return True
    except jwt.exceptions.InvalidTokenError as e:
        logger.exception(e)
        logger.debug(auth_header_value)

    return False

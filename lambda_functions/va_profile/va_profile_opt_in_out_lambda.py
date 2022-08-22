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
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm.html
    https://boto3.amazonaws.com/v1/documentation/api/latest/guide/error-handling.html

The execution role that imports the module is not the same execution role that executes
the handler.  Make calls to SSM Parameter Store from within the handler to avoid a
hard-to-identify permissions problem that results in the lambda call timing-out.
"""

import boto3
import jwt
import logging
import os
import psycopg2
import ssl
import sys
from botocore.exceptions import ClientError
from cryptography.x509 import Certificate, load_pem_x509_certificate
from http.client import HTTPSConnection
from json import dumps
from typing import Optional

logger = logging.getLogger("VAProfileOptInOut")
logger.setLevel(logging.DEBUG)

OPT_IN_OUT_QUERY = """SELECT va_profile_opt_in_out(%s, %s, %s, %s, %s);"""
NOTIFY_ENVIRONMENT = os.getenv("NOTIFY_ENVIRONMENT")
# TODO - Make this an SSM call.  Consolidate all parameter calls.
SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI")
VA_PROFILE_DOMAIN = os.getenv("VA_PROFILE_DOMAIN")
VA_PROFILE_PATH_BASE = "/communication-hub/communication/v1/status/changelog/"


if NOTIFY_ENVIRONMENT is None:
    # Without this value, this code cannot know the path to the required
    # SSM Parameter Store values.
    sys.exit("NOTIFY_ENVIRONMENT is not set.  Cannot authenticate requests.")


# TODO - Make this an SSM call.
if SQLALCHEMY_DATABASE_URI is None:
    logger.error("SQLALCHEMY_DATABASE_URI is not set.")
    sys.exit("Couldn't connect to the database.")


# This is a public certificate in .pem format.  Use it to verify the signature
# of the JWT contained in POST requests from VA Profile.
va_profile_public_cert = None
requested_va_profile_public_cert = False


def get_va_profile_public_cert() -> Certificate:
    """
    Get the VA Profile public certificate pem from AWS SSM Parameter Store.
    """

    assert not requested_va_profile_public_cert, "Don't call this function more than once."
    assert VA_PROFILE_DOMAIN is not None, "There's no point getting a value that won't be used."
    the_pem = None

    logger.debug("Getting the VA Profile public pem from SSM . . .")
    ssm_client = boto3.client("ssm")

    try:
        response = ssm_client.get_parameter(
            Name=f"/{NOTIFY_ENVIRONMENT}/notification-api/va-profile/va-profile-public-pem",
            WithDecryption=True
        )
    except ClientError as e:
        logger.exception(e)
        return None

    the_pem = response.get("Parameter", {}).get("Value")

    if the_pem is None:
        logger.error("Couldn't get the VA Profile public pem.  Unable to authenticate POST requests.")
        logger.debug(response)
        sys.exit("Unable to verify JWTs in POST requests.")
    else:
        logger.debug("Retrieved the VA Profile public pem.")

        try:
            va_profile_public_cert = load_pem_x509_certificate(the_pem.encode()).public_key()
        except ValueError as e:
            logger.exception(e)
            logger.debug("the_pem =\n%s", the_pem)
            sys.exit("Unable to verify JWTs in POST requests.")

    return va_profile_public_cert


# This is the VA root chain used to verify the certiicate VA Profile uses for 2-way TLS when
# this code makes a PUT request to a VA Profile endpoint.
va_root_pem = None
requested_va_root_pem = False


def get_va_root_pem() -> Optional[str]:
    """
    Get the VA root certificate pem chain from AWS SSM Parameter Store.
    """

    assert not requested_va_root_pem, "Don't call this function more than once."
    assert NOTIFY_ENVIRONMENT != "test"
    the_pem = None

    logger.debug("Getting the VA root pem from SSM . . .")
    ssm_client = boto3.client("ssm")

    try:
        response = ssm_client.get_parameter(
            Name=f"/{NOTIFY_ENVIRONMENT}/notification-api/va-profile/va-root-pem",
            WithDecryption=True
        )
    except ClientError as e:
        logger.exception(e)
        return None

    the_pem = response.get("Parameter", {}).get("Value")

    if the_pem is None:
        logger.error("Couldn't get the VA root chain.  Unable to make PUT requests.")
        logger.debug(response)
    else:
        logger.debug("Retrieved the VA root pem.")

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
            "bios": [{
                "txAuditId": "string",
                "sourceDate": "2022-03-07T19:37:59.320Z",
                "vaProfileId": 0,
                "communicationChannelId": 0,
                "communicationItemId": 0,
                "allowed": true,
                ...
            }],
        }

    "bios" is a list of dictionaries, but we only expect it to have one element for reasons documented here:
        https://github.com/department-of-veterans-affairs/notification-api/issues/704#issuecomment-1198427986

    When this function is called from a unit test, the database URI will differ slightly from the environment
    variable, SQLALCHEMY_DATABASE_URI.  The parameter worker_id is used to construct the modified name in the
    same manner as in the tests/conftest.py::notify_db fixture.
    """

    logger.debug(event)
    global requested_va_profile_public_cert, va_profile_public_cert, requested_va_root_pem, va_root_pem

    if not requested_va_profile_public_cert:
        va_profile_public_cert = get_va_profile_public_cert()
        requested_va_profile_public_cert = True

    headers = event.get("headers", {})
    if not jwt_is_valid(headers.get("Authorization", headers.get("authorization", '')), va_profile_public_cert):
        return { "statusCode": 401 }

    post_body = event["body"]

    if "txAuditId" not in post_body or "bios" not in post_body or not isinstance(post_body["bios"], list):
        return { "statusCode": 400, "body": "A required top level attribute is missing from the request body or has the wrong type." }

    post_response = { "statusCode": 200 }

    if len(post_body["bios"]) > 1:
        # Refer to https://github.com/department-of-veterans-affairs/notification-api/issues/704#issuecomment-1198427986
        logger.warning("The POST request contains more than one update.  Only the first will be processed.")

    bio = post_body["bios"][0]

    put_body = {"dateTime": bio["sourceDate"]}

    if bio.get("txAuditId", '') != post_body["txAuditId"]:
        put_body["status"] = "COMPLETED_FAILURE"
        put_body["messages"] = [{
            "text": "The record's txAuditId, {}, does not match the event's txAuditId, {}.".format(bio.get("txAuditId", "<unknown>"), post_body["txAuditId"]),
            "severity": "ERROR",
            "potentiallySelfCorrectingOnRetry": False,
        }]
        make_PUT_request(post_body["txAuditId"], put_body)
        return post_response

    # VA Profile filters on their end and should only sent us records that match a criteria.
    if bio.get("communicationItemId", -1) != 5 or bio.get("communicationChannelId", -1) != 2:
        put_body["status"] = "COMPLETED_NOOP"
        make_PUT_request(post_body["txAuditId"], put_body)
        return post_response

    try:
        params = (                          # Stored function parameters:
            bio["vaProfileId"],             #     _va_profile_id
            bio["communicationItemId"],     #     _communication_item_id
            bio["communicationChannelId"],  #     _communication_channel_name
            bio["allowed"],                 #     _allowed
            bio["sourceDate"],              #     _source_datetime
        )

        global db_connection

        if db_connection is None or db_connection.status != 0:
            # Attempt to (re-)establish a database connection
            db_connection = make_connection(worker_id)

        if db_connection is None:
            raise RuntimeError("No database connection.")

        # Execute the stored function.
        with db_connection.cursor() as c:
            # https://www.psycopg.org/docs/cursor.html#cursor.execute
            c.execute(OPT_IN_OUT_QUERY, params)
            put_body["status"] = "COMPLETED_SUCCESS" if c.fetchone()[0] else "COMPLETED_NOOP"
            db_connection.commit()
    except KeyError as e:
        # Bad Request.  Required attributes are missing.
        post_response["statusCode"] = 400
        put_body["status"] = "COMPLETED_FAILURE"
        logger.exception(e)
    except Exception as e:
        # Internal Server Error.
        post_response["statusCode"] = 500
        put_body["status"] = "COMPLETED_FAILURE"
        logger.exception(e)
    finally:
        # Make a PUT request to VA Profile if appropriate and possible.
        if VA_PROFILE_DOMAIN is not None:
            if not requested_va_root_pem and NOTIFY_ENVIRONMENT != "test":
                va_root_pem = get_va_root_pem()
                requested_va_root_pem = True

            if va_root_pem is not None or NOTIFY_ENVIRONMENT == "test":
                make_PUT_request(post_body["txAuditId"], put_body)

    return post_response


def jwt_is_valid(auth_header_value: str, public_key: Certificate) -> bool:
    """
    VA Profile should have sent an asymmetrically signed JWT with their POST request.
    """

    assert public_key is not None
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
        jwt.decode(token, public_key, algorithms=["RS256"], options=options)
        return True
    except (jwt.exceptions.InvalidTokenError, TypeError) as e:
        logger.exception(e)

    return False


def make_PUT_request(tx_audit_id: str, body: dict):
    global ssl_context, va_root_pem
    assert NOTIFY_ENVIRONMENT != "test", "Don't make PUT requests during unit testing."
    assert VA_PROFILE_DOMAIN is not None, "What is the domain of the PUT request?"
    assert va_root_pem is not None

    try:
        if ssl_context is None:
            # Use the VA root .pem to authenticate VA Profile's server.
            ssl_context = ssl.create_default_context(cadata=va_root_pem)

        try:
            # Make a PUT request to VA Profile.
            https_connection = HTTPSConnection(VA_PROFILE_DOMAIN, context=ssl_context)

            https_connection.request(
                "PUT",
                VA_PROFILE_PATH_BASE + tx_audit_id,
                body,
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


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
import json
import jwt
import logging
import os
import psycopg2
import ssl
import sys
from botocore.exceptions import ClientError
from cryptography.x509 import Certificate, load_pem_x509_certificate
from http.client import HTTPSConnection
from typing import Optional, Tuple

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
# on the JWT contained in POST requests from VA Profile.
va_profile_public_cert = None

# This is the VA root chain used to verify the certiicate VA Profile uses for 2-way TLS when
# this code makes a PUT request to a VA Profile endpoint.
va_root_pem = None

# Only make one request to SSM Parameter Store.  The above two variables are module-level
# so a new request doesn't need to be made for each HTTP request received during the
# life of the execution environment.
requested_certificates = False


def get_certificates_from_ssm() -> Tuple[Optional[Certificate], Optional[Certificate]]:
    """
    Query AWS SSM Parameter Store to get the VA Profile public certificate and the VA root
    certificate chain.
    """

    assert not requested_certificates, "Don't call this function more than once."

    PROFILE_CERT_NAME = f"/{NOTIFY_ENVIRONMENT}/notification-api/va-profile/va-profile-public-pem"
    VA_CERT_NAME = f"/{NOTIFY_ENVIRONMENT}/notification-api/va-profile/va-root-pem"

    ssm_client = boto3.client("ssm")
    logger.debug("Getting certificates from SSM Parameter Store . . .")

    try:
        response = ssm_client.get_parameters(
            Names=[
                PROFILE_CERT_NAME,
                VA_CERT_NAME,
            ],
            WithDecryption=True
        )
    except ClientError as e:
        logger.exception(e)
        return (None, None)

    logger.debug(". . . Retrieved certificates from SSM Parameter Store.")

    invalid_parameters =  response.get("InvalidParameters", [])
    if invalid_parameters:
        logger.error("Couldn't get these parameters from SSM Parameter Store: %s", invalid_parameters)

    profile_cert = None
    va_cert = None

    for parameter in response.get("Parameters", []):
        name = parameter.get("Name", '')

        if name == PROFILE_CERT_NAME:
            if profile_cert is not None:
                logger.warning("Parameter Store returned multiple values for %s.", name)

            try:
                # The call to str.encode converts the string to a bytes object.
                profile_cert = load_pem_x509_certificate(parameter.get("Value", '').encode()).public_key()
            except ValueError as e:
                logger.exception(e)
                logger.debug("Cannot get the Profile public certificate from:\n%s", parameter.get("Value", "the empty string"))
        elif name == VA_CERT_NAME:
            if va_cert is not None:
                logger.warning("Parameter Store returned multiple values for %s.", name)
            va_cert = parameter.get("Value")
        elif not name:
            logger.debug("Parameter Store returned a parameter without a name.")
        else:
            logger.debug("Parameter Store returned an unsolicited parameter: %s", name)

    return (profile_cert, va_cert)


def make_connection(worker_id):
    """
    Return a connection to the database, or return None.

    https://www.psycopg.org/docs/module.html#psycopg2.connect
    https://www.psycopg.org/docs/module.html#exceptions
    """

    logger.debug("Connecting to the database . . .")
    connection = None

    try:
        connection = psycopg2.connect(SQLALCHEMY_DATABASE_URI + ('' if worker_id is None else f"_{worker_id}"))
        logger.debug(". . . Connected to the database.")
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
    Use the event data to process veterans' opt-in/out requests as relayed by VA Profile.  The event is as
    proxied by the API gateway or application load balancer:
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

    logger.debug("POST event: %s", event)
    global requested_certificates, va_profile_public_cert, va_root_pem

    if not requested_certificates:
        va_profile_public_cert, va_root_pem = get_certificates_from_ssm()

        if va_profile_public_cert is None:
            sys.exit("Cannot verify JWT signatures on POST requests from VA Profile.")

        requested_certificates = True

    # Authenticate the request from VA Profile.
    headers = event.get("headers", {})
    if not jwt_is_valid(headers.get("Authorization", headers.get("authorization", '')), va_profile_public_cert):
        return { "statusCode": 401 }

    post_body = event["body"]

    if isinstance(post_body, (bytes, str)):
        try:
            post_body = json.loads(post_body)
        except json.decoder.JSONDecodeError:
            return { "statusCode": 400, "body": "malformed JSON" }

    if not isinstance(post_body, dict):
        return { "statusCode": 400, "body": "The request body should be a JSON object." }

    if "txAuditId" not in post_body or "bios" not in post_body or not isinstance(post_body["bios"], list):
        return { "statusCode": 400, "body": "A required top level attribute is missing from the request body or has the wrong type." }

    post_response = { "statusCode": 200 }

    if len(post_body["bios"]) > 1:
        # Refer to https://github.com/department-of-veterans-affairs/notification-api/issues/704#issuecomment-1198427986
        logger.warning("The POST request contains more than one update.  Only the first will be processed.")

    bio = post_body["bios"][0]

    put_body = {"dateTime": bio["sourceDate"]}

    if bio.get("txAuditId", '') != post_body["txAuditId"]:
        if (va_root_pem is not None or NOTIFY_ENVIRONMENT == "test") and VA_PROFILE_DOMAIN is not None:
            put_body["status"] = "COMPLETED_FAILURE"
            put_body["messages"] = [{
                "text": "The record's txAuditId, {}, does not match the event's txAuditId, {}.".format(bio.get("txAuditId", "<unknown>"), post_body["txAuditId"]),
                "severity": "ERROR",
                "potentiallySelfCorrectingOnRetry": False,
            }]
            make_PUT_request(post_body["txAuditId"], put_body)
        return post_response

    # VA Profile filters on their end and should only sent us records that match a criteria.
    # communicationChannelId 1 signifies SMS; 2, e-mail.
    if bio.get("communicationItemId", -1) != 5 or bio.get("communicationChannelId", -1) != 1:
        if (va_root_pem is not None or NOTIFY_ENVIRONMENT == "test") and VA_PROFILE_DOMAIN is not None:
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
            # Attempt to (re-)establish a database connection.
            db_connection = make_connection(worker_id)

        if db_connection is None:
            raise RuntimeError("No database connection.")

        # Execute the stored function.
        logger.debug("Executing the stored function . . .")
        with db_connection.cursor() as c:
            # https://www.psycopg.org/docs/cursor.html#cursor.execute
            c.execute(OPT_IN_OUT_QUERY, params)
            put_body["status"] = "COMPLETED_SUCCESS" if c.fetchone()[0] else "COMPLETED_NOOP"
            db_connection.commit()
        logger.debug(". . . Executed the stored function.")
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
        if (va_root_pem is not None or NOTIFY_ENVIRONMENT == "test") and VA_PROFILE_DOMAIN is not None:
            assert bool(put_body.get("status"))
            make_PUT_request(post_body["txAuditId"], put_body)

    logger.debug("POST response: %s", post_response)
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
    assert isinstance(VA_PROFILE_DOMAIN, str), "What is the domain of the PUT request?"
    assert va_root_pem is not None, "Can't verify the authenticity of the server."
    assert isinstance(tx_audit_id, str)
    logger.debug("PUT request body: %s", body)

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
                json.dumps(body),
                { "Content-Type": "application/json" }
            )

            put_response = https_connection.getresponse()

            logger.info("VA Profile responded to the PUT request with HTTP status %d.", put_response.status)
            if put_response.status != 200:
                logger.debug(put_response)
        except ConnectionError as e:
            logger.error("The PUT request to VA Profile failed.")
            logger.exception(e)
        except Exception as e:
            # TODO - Make this more specific.  Is it a timeout?
            logger.error("The PUT request to VA Profile failed.")
            logger.exception(e)
        finally:
            https_connection.close()
    except ssl.SSLError as e:
        logger.exception(e)

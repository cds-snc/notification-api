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
    https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/acm.html#ACM.Client.export_certificate

The execution role that imports the module is not the same execution role that executes
the handler.  Make boto3 calls from within the handler to avoid a hard-to-identify
permissions problem that results in the lambda call timing-out.

The execution environment varies according to how this code is run.  During testing (local or via Github Action),
the environment is a container with the full contents of the notification-api repository.  In an AWS deployment
envronment, it is the Lambda execution environment, which should make certain files available in the /opt directory
via lambda layers.
"""

import boto3
import json
import jwt
import logging
import os
import psycopg2
import ssl
import sys
from botocore.exceptions import ClientError, ValidationError
from cryptography.x509 import Certificate, load_pem_x509_certificate
from http.client import HTTPSConnection
from tempfile import NamedTemporaryFile


logger = logging.getLogger("VAProfileOptInOut")
logger.setLevel(logging.DEBUG)

CERTIFICATE_ARN = os.getenv("CERTIFICATE_ARN")
OPT_IN_OUT_QUERY = """SELECT va_profile_opt_in_out(%s, %s, %s, %s, %s);"""
NOTIFY_ENVIRONMENT = os.getenv("NOTIFY_ENVIRONMENT")
ALB_PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH")
# TODO - Make this an SSM call.
SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI")
VA_PROFILE_DOMAIN = os.getenv("VA_PROFILE_DOMAIN")
VA_PROFILE_PATH_BASE = "/communication-hub/communication/v1/status/changelog/"


if NOTIFY_ENVIRONMENT is None:
    # Without this value, this code cannot know the path to the required
    # SSM Parameter Store values and other resources.
    sys.exit("NOTIFY_ENVIRONMENT is not set.")


if NOTIFY_ENVIRONMENT == "test":
    jwt_certificate_path = "tests/lambda_functions/va_profile/cert.pem"
elif NOTIFY_ENVIRONMENT == "prod":
    jwt_certificate_path = "/opt/Profile_prod_public.pem"
else:
    jwt_certificate_path = "/opt/Profile_nonprod_public.pem"

# Load VA Profile's public certificate used to verify JWT signatures for POST requests.
# In deployment environments, the certificate should be available via a lambda layer.
try:
    with open(jwt_certificate_path, "rb") as f:
        va_profile_public_cert = load_pem_x509_certificate(f.read()).public_key()
except (OSError, ValueError) as e:
    logger.exception(e)
    sys.exit("The JWT public certificate is missing or invalid.  Cannot authenticate POST requests.")

# Integration testing uses a different certificate pair because VA Notify does not have
# access to VA Profile's private key.  This variable with be populated later if needed.
integration_testing_public_cert = None

# TODO - make SSM call; delete this block
if SQLALCHEMY_DATABASE_URI is None:
    logger.error("SQLALCHEMY_DATABASE_URI is not set.")
    sys.exit("Couldn't connect to the database.")


# Making PUT requests requires presenting client certificates for mTLS.  These are used programmatically via ssl.SSLContext.
# The certificates are not necessary for testing, wherein the PUT request is mocked.
ssl_context = None

if CERTIFICATE_ARN is None:
    logger.error("CERTIFICATE_ARN is not set.")
elif ALB_PRIVATE_KEY_PATH is None:
    logger.error("ALB_PRIVATE_KEY_PATH is not set.")
elif NOTIFY_ENVIRONMENT != "test":
    try:
        # Get the client certificates from AWS ACM.
        logger.debug("Making a request to ACM . . .")
        acm_client = boto3.client("acm")
        acm_response: dict = acm_client.get_certificate(CertificateArn=CERTIFICATE_ARN)
        logger.debug(". . . Finished the request to ACM.")

        # Get the private key from SSM Parameter Store.
        # TODO - Get the database URI too.
        logger.debug("Getting the ALB private key from SSM Parameter Store . . .")
        ssm_client = boto3.client("ssm")
        ssm_response: dict = ssm_client.get_parameter(
            Name=ALB_PRIVATE_KEY_PATH,
            WithDecryption=True
        )
        logger.debug(". . . Retrieved the ALB private key from SSM Parameter Store.")

        with NamedTemporaryFile() as f:
            f.write(acm_response["Certificate"].encode())
            f.write(acm_response["CertificateChain"].encode())
            f.write(ssm_response["Parameter"]["Value"].encode())
            f.seek(0)

            ssl_context = ssl.create_default_context(cadata=acm_response["CertificateChain"])
            ssl_context.load_cert_chain(f.name)
    except (OSError, ClientError, ssl.SSLError, ValidationError) as e:
        logger.exception(e)
        if isinstance(e, ssl.SSLError):
            logger.error("The reason is: %s", e.reason)
        ssl_context = None

should_make_put_request = (NOTIFY_ENVIRONMENT == "test") or (VA_PROFILE_DOMAIN is not None and ssl_context is not None)
if not should_make_put_request:
    logger.error("Cannot make PUT requests.")


db_connection = None

def make_database_connection(worker_id):
    """
    Return a connection to the database, or return None.

    https://www.psycopg.org/docs/module.html#psycopg2.connect
    https://www.psycopg.org/docs/module.html#exceptions
    """

    connection = None

    try:
        logger.debug("Connecting to the database . . .")
        connection = psycopg2.connect(SQLALCHEMY_DATABASE_URI + ('' if worker_id is None else f"_{worker_id}"))
        logger.debug(". . . Connected to the database.")
    except psycopg2.Warning as e:
        logger.warning(e)
    except psycopg2.Error as e:
        logger.exception(e)
        logger.error(e.pgcode)

    return connection


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
                "communicationChannelId": 1,
                "communicationItemId": 5,
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
    global va_profile_public_cert, integration_testing_public_cert

    headers = event.get("headers", {})
    is_integration_test = event.get("path", '').endswith("?integration_test")

    if is_integration_test and integration_testing_public_cert is None:
        # This request is part of integration testing and should be authenticated using a certificate
        # specifically for that purpose.
        integration_testing_public_cert = get_integration_testing_public_cert()
        assert integration_testing_public_cert is not None

    # Authenticate the POST request by verifying the JWT signature.
    if not jwt_is_valid(
        headers.get("Authorization", headers.get("authorization", '')),
        integration_testing_public_cert if is_integration_test else va_profile_public_cert
    ):
        return { "statusCode": 401 }

    post_body = event.get("body")

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
        if should_make_put_request:
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
        if should_make_put_request:
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
            db_connection = make_database_connection(worker_id)

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
        if should_make_put_request:
            assert bool(put_body.get("status"))
            make_PUT_request(post_body["txAuditId"], put_body)

    logger.debug("POST response: %s", post_response)

    if is_integration_test:
        post_response["put_body"] = put_body

    return post_response


def jwt_is_valid(auth_header_value: str, public_key: Certificate) -> bool:
    """
    The POST request should have sent an asymmetrically signed JWT.  Attempt to verify the signature.
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
    global ssl_context
    assert isinstance(VA_PROFILE_DOMAIN, str), "What is the domain of the PUT request?"
    assert isinstance(tx_audit_id, str)
    logger.debug("PUT request body: %s", body)

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


def get_integration_testing_public_cert() -> Certificate:
    """
    Load the integration testing public certificate used to verify JWT signatures for POST requests.
    In deployment environments, the certificate should be available via a lambda layer.  Mock this
    function during unit testing.
    """

    assert NOTIFY_ENVIRONMENT != "test"

    try:
        with open("/opt/Notify_integration_testing_public.pem", "rb") as f:
            return load_pem_x509_certificate(f.read()).public_key()
    except Exception as e:
        logger.exception(e)

    sys.exit("The integration testing public certificate is missing or invalid.  Cannot authenticate POST requests.")

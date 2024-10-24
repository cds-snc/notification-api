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

The execution environment varies according to how this code is run.  During testing (local or via Github Action),
the environment is a container with the full contents of the notification-api repository.  In an AWS deployment
envronment, it is the Lambda execution environment, which should make certain files available in the /opt directory
via lambda layers.
"""

import calendar
import json
import logging
import os
import ssl
import sys
from datetime import datetime, timezone
from http.client import HTTPSConnection, HTTPResponse
from tempfile import NamedTemporaryFile
from typing import Optional

import boto3
import jwt
import psycopg2
from botocore.exceptions import ClientError, ValidationError
from cryptography.x509 import Certificate, load_pem_x509_certificate


logger = logging.getLogger('VAProfileOptInOut')
logger.setLevel(getattr(logging, os.getenv('LOG_LEVEL', 'DEBUG')))

ALB_CERTIFICATE_ARN = os.getenv('ALB_CERTIFICATE_ARN')
ALB_PRIVATE_KEY_PATH = os.getenv('ALB_PRIVATE_KEY_PATH')
CA_PATH = '/opt/VA_CAs/'
COMP_AND_PEN_OPT_IN_CUTOFF_TIME_UTC = 11, 10, 0, 0
COMP_AND_PEN_OPT_IN_API_KEY_PARAM_PATH = os.getenv('COMP_AND_PEN_OPT_IN_API_KEY')
COMP_AND_PEN_OPT_IN_TEMPLATE_ID = os.getenv('COMP_AND_PEN_OPT_IN_TEMPLATE_ID')
COMP_AND_PEN_SERVICE_ID = os.getenv('COMP_AND_PEN_SERVICE_ID')
COMP_AND_PEN_SMS_SENDER_ID = os.getenv('COMP_AND_PEN_SMS_SENDER_ID')
NOTIFY_ENVIRONMENT = os.getenv('NOTIFY_ENVIRONMENT')
OPT_IN_OUT_QUERY = """SELECT va_profile_opt_in_out(%s, %s, %s, %s, %s);"""
OPT_IN_OUT_ADD_NOTIFICATION_ID_QUERY = (
    """ UPDATE va_profile_local_cache SET notification_id = %s WHERE va_profile_id = %s AND source_datetime = %s; """
)
VA_PROFILE_DOMAIN = os.getenv('VA_PROFILE_DOMAIN')
VA_PROFILE_PATH_BASE = '/communication-hub/communication/v1/status/changelog/'
VA_NOTIFY_SEND_SMS_PATH = '/v2/notifications/sms'

# Build domain based on environment
if NOTIFY_ENVIRONMENT == 'prod':
    VA_NOTIFY_DOMAIN = 'api.notifications.va.gov'
else:
    VA_NOTIFY_DOMAIN = f'{NOTIFY_ENVIRONMENT}.api.notifications.va.gov'


if NOTIFY_ENVIRONMENT is None:
    sys.exit('NOTIFY_ENVIRONMENT is not set.  Check the Lambda console.')

if NOTIFY_ENVIRONMENT != 'test' and not os.path.isdir(CA_PATH):
    sys.exit('The VA CA certificate directory is missing.  Is the lambda layer in use?')

if NOTIFY_ENVIRONMENT == 'test':
    jwt_certificate_path = 'tests/lambda_functions/va_profile/cert.pem'
elif NOTIFY_ENVIRONMENT == 'prod':
    jwt_certificate_path = '/opt/jwt/Profile_prod_public.pem'
else:
    jwt_certificate_path = '/opt/jwt/Profile_nonprod_public.pem'

# Load VA Profile's public certificate used to verify JWT signatures for POST requests.
# In deployment environments, the certificate should be available via a lambda layer.
try:
    with open(jwt_certificate_path, 'rb') as f:
        va_profile_public_cert = load_pem_x509_certificate(f.read()).public_key()
except (OSError, ValueError) as e:
    logger.exception(e)
    sys.exit('The JWT public certificate is missing or invalid.  Cannot authenticate POST requests.')

# Integration testing uses a different certificate pair because VA Notify does not have
# access to VA Profile's private key.  This variable with be populated later if needed.
integration_testing_public_cert = None

# Get the database URI.
if NOTIFY_ENVIRONMENT == 'test':
    sqlalchemy_database_uri = os.getenv('SQLALCHEMY_DATABASE_URI')
else:
    # This is an AWS deployment environment.
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


# Making PUT requests requires presenting client certificates for mTLS.  These are used programmatically via ssl.SSLContext.
# The certificates are not necessary for testing, wherein the PUT request is mocked.
ssl_context = None

# Use mock API Key in env variables for testing, else set to None
# Outside of testing, COMP_AND_PEN_OPT_IN_API_KEY is defined by its paramater store value
COMP_AND_PEN_OPT_IN_API_KEY = os.getenv('COMP_AND_PEN_OPT_IN_API_KEY', None)

if ALB_CERTIFICATE_ARN is None:
    logger.error('ALB_CERTIFICATE_ARN is not set.')
elif ALB_PRIVATE_KEY_PATH is None:
    logger.error('ALB_PRIVATE_KEY_PATH is not set.')
elif NOTIFY_ENVIRONMENT != 'test':
    try:
        # Get the client certificates from AWS ACM.
        logger.debug('Making a request to ACM . . .')
        acm_client = boto3.client('acm')
        acm_response: dict = acm_client.get_certificate(CertificateArn=ALB_CERTIFICATE_ARN)
        logger.debug('. . . Finished the request to ACM.')

        # Get the private key from SSM Parameter Store.
        logger.debug('Getting the ALB private key from SSM Parameter Store . . .')
        ssm_client = boto3.client('ssm')
        ssm_response: dict = ssm_client.get_parameter(Name=ALB_PRIVATE_KEY_PATH, WithDecryption=True)
        logger.debug('. . . Retrieved the ALB private key from SSM Parameter Store.')

        # Include all VA CA certificates in the default SSL environment.
        # ssl_context = ssl.create_default_context(capath=CA_PATH)
        # TODO - This is a workaround.  The capath approach doesn't seem to load anything.  See issue #1063.
        ssl_context = ssl.create_default_context(cafile=f'{CA_PATH}VA-Internal-S2-ICA11.cer')
        ssl_context.load_verify_locations(cafile=f'{CA_PATH}VA-Internal-S2-RCA2.cer')

        with NamedTemporaryFile() as f:
            f.write(acm_response['Certificate'].encode())
            f.write(acm_response['CertificateChain'].encode())
            f.write(ssm_response['Parameter']['Value'].encode())
            f.seek(0)

            ssl_context.load_cert_chain(f.name)

        # Get Comp and Pen API Key from Parameter Store
        ssm_response_api_key = ssm_client.get_parameter(
            Name=COMP_AND_PEN_OPT_IN_API_KEY_PARAM_PATH, WithDecryption=True
        )
        COMP_AND_PEN_OPT_IN_API_KEY = ssm_response_api_key['Parameter']['Value']
    except (OSError, ClientError, ssl.SSLError, ValidationError, KeyError) as e:
        logger.exception(e)
        if isinstance(e, ssl.SSLError):
            logger.error('The reason is: %s', e.reason)
        ssl_context = None

should_make_put_request = (NOTIFY_ENVIRONMENT == 'test') or (VA_PROFILE_DOMAIN is not None and ssl_context is not None)
if not should_make_put_request:
    logger.error('Cannot make PUT requests.')


db_connection = None


def make_database_connection():
    """
    Return a connection to the database, or return None.

    https://www.psycopg.org/docs/module.html#psycopg2.connect
    https://www.psycopg.org/docs/module.html#exceptions
    """

    connection = None

    try:
        logger.debug('Connecting to the database . . .')
        connection = psycopg2.connect(sqlalchemy_database_uri)
        logger.debug('. . . Connected to the database.')
    except psycopg2.Warning as e:
        logger.warning(e)
    except psycopg2.Error as e:
        logger.exception(e)
        logger.error(e.pgcode)

    return connection


def va_profile_opt_in_out_lambda_handler(  # noqa: C901
    event: dict,
    context,
) -> dict:
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
    """

    logger.info('POST request received.')
    logger.debug('POST event: %s', event)

    global va_profile_public_cert, integration_testing_public_cert

    headers = event.get('headers', {})
    is_integration_test = 'integration_test' in event.get('queryStringParameters', {})
    if is_integration_test:
        logger.debug('This request is an integration test.')

    if is_integration_test and integration_testing_public_cert is None:
        # This request is part of integration testing and should be authenticated using a certificate
        # specifically for that purpose.
        integration_testing_public_cert = get_integration_testing_public_cert()
        assert integration_testing_public_cert is not None

    # Authenticate the POST request by verifying the JWT signature.
    if not jwt_is_valid(
        headers.get('Authorization', headers.get('authorization', '')),
        integration_testing_public_cert if is_integration_test else va_profile_public_cert,
    ):
        logger.info('Authentication failed.  Returning 401.')
        return {'statusCode': 401}

    post_body = event.get('body')

    if isinstance(post_body, (bytes, str)):
        try:
            post_body = json.loads(post_body)
        except json.decoder.JSONDecodeError:
            logger.info('Malformed JSON.  Returning 400.')
            return {'statusCode': 400, 'body': 'malformed JSON'}

    if not isinstance(post_body, dict):
        logger.info('The request body should be a JSON object.  Returning 400.')
        return {'statusCode': 400, 'body': 'The request body should be a JSON object.'}

    if 'txAuditId' not in post_body or 'bios' not in post_body or not isinstance(post_body['bios'], list):
        logger.info(
            'A required top level attribute is missing from the request body or has the wrong type.  Returning 400.'
        )
        return {
            'statusCode': 400,
            'body': 'A required top level attribute is missing from the request body or has the wrong type.',
        }

    post_response = {'statusCode': 200}

    if len(post_body['bios']) > 1:
        # Refer to https://github.com/department-of-veterans-affairs/notification-api/issues/704#issuecomment-1198427986
        logger.warning('The POST request contains more than one update.  Only the first will be processed.')

    bio = post_body['bios'][0]
    put_body = {'dateTime': bio.get('sourceDate', 'not available')}

    if bio.get('txAuditId', '') != post_body['txAuditId']:
        if should_make_put_request:
            put_body['status'] = 'COMPLETED_FAILURE'
            put_body['messages'] = [
                {
                    'text': "The record's txAuditId, {}, does not match the event's txAuditId, {}.".format(
                        bio.get('txAuditId', '<unknown>'), post_body['txAuditId']
                    ),
                    'severity': 'ERROR',
                    'potentiallySelfCorrectingOnRetry': False,
                }
            ]
            make_PUT_request(post_body['txAuditId'], put_body)

            if is_integration_test:
                post_response['headers'] = {
                    'Content-Type': 'application/json',
                }
                post_response['body'] = json.dumps(
                    {
                        'put_body': put_body,
                    }
                )

        logger.info('POST response: %s', post_response)
        return post_response

    # VA Profile filters on their end and should only sent us records that match a criteria.
    # communicationChannelId 1 signifies SMS; 2, e-mail.
    if bio.get('communicationItemId', -1) != 5 or bio.get('communicationChannelId', -1) != 1:
        if should_make_put_request:
            put_body['status'] = 'COMPLETED_NOOP'
            make_PUT_request(post_body['txAuditId'], put_body)

            if is_integration_test:
                post_response['headers'] = {
                    'Content-Type': 'application/json',
                }
                post_response['body'] = json.dumps(
                    {
                        'put_body': put_body,
                    }
                )

        logger.info('POST response: %s', post_response)
        return post_response

    try:
        # Stored function parameters:
        params = (
            bio['vaProfileId'],  # _va_profile_id
            bio['communicationItemId'],  # _communication_item_id
            bio['communicationChannelId'],  # _communication_channel_name
            bio['allowed'],  # _allowed
            bio['sourceDate'],  # _source_datetime
        )

        logger.info(
            'The request is an opt-%s.',
            'in' if (str(bio['allowed']).lower() == 'true') else 'out',
        )

        global db_connection

        if db_connection is None or db_connection.status != 0:
            # Attempt to (re-)establish a database connection.
            db_connection = make_database_connection()

        if db_connection is None:
            raise RuntimeError('No database connection.')

        with db_connection.cursor() as c:
            # https://www.psycopg.org/docs/cursor.html#cursor.execute
            c.execute(OPT_IN_OUT_QUERY, params)
            put_body['status'] = 'COMPLETED_SUCCESS' if c.fetchone()[0] else 'COMPLETED_NOOP'
            db_connection.commit()

        logger.debug('Executed the stored function.')
    except KeyError as e:
        # Bad Request.  Required attributes are missing.
        post_response['statusCode'] = 400
        put_body['status'] = 'COMPLETED_FAILURE'
        put_body['messages'] = [
            {
                'text': f'KeyError: The bios dictionary attribute is missing the required attribute {e}.',
                'severity': 'ERROR',
                'potentiallySelfCorrectingOnRetry': False,
            }
        ]
        logger.exception(e)
    except Exception as e:
        # Internal Server Error.
        post_response['statusCode'] = 500
        put_body['status'] = 'COMPLETED_FAILURE'
        put_body['messages'] = [
            {
                'text': str(e),
                'severity': 'ERROR',
                'potentiallySelfCorrectingOnRetry': False,
            }
        ]
        logger.exception(e)
    finally:
        if should_make_put_request:
            assert bool(put_body.get('status')), 'The PUT request must include a non-empty status.'
            make_PUT_request(post_body['txAuditId'], put_body)

            if is_integration_test:
                post_response['headers'] = {
                    'Content-Type': 'application/json',
                }
                post_response['body'] = json.dumps(
                    {
                        'put_body': put_body,
                    }
                )

        va_profile_id = bio['vaProfileId']

    try:
        # Send Comp and Pen Opt-In confirmation if anticipated status code still 200
        # And if Opt-In confirmation (bio['allowed'] == True)
        if post_response['statusCode'] == 200 and bio['allowed']:
            response = send_comp_and_pen_opt_in_confirmation(va_profile_id)

            # Save notification_id from POST sms response if method returned
            # a value AND the response status code is 201.
            if response is None:
                logger.critical(
                    'Could not send Comp and Pen opt-in confirmation to VAProfileId: %s. No response status or response body to record.',
                    va_profile_id,
                )
            elif response.status != 201:
                response_data = response.read().decode()
                response_json = json.loads(response_data)
                logger.critical(
                    'Could not send Comp and Pen opt-in confirmation to VAProfileId: %s. Response status: %s, Response: %s',
                    va_profile_id,
                    response.status,
                    response_data,
                )
            else:
                response_data = response.read().decode()
                response_json = json.loads(response_data)
                notification_id = response_json['id']

                logger.info(
                    'Sent Comp and Pen opt-in confirmation to VAProfileId: %s with notification_id: %s. Response status: %s',
                    va_profile_id,
                    notification_id,
                    response.status,
                )
                save_notification_id_to_cache(va_profile_id, notification_id, bio['sourceDate'])

    except Exception as e:
        logger.critical(
            'Critical error during the process of sending a Comp and Pen Opt-in confirmation notification to VaProfileId: %s. Error: %s',
            va_profile_id,
            e,
        )

    logger.info('POST response: %s', post_response)
    return post_response


def jwt_is_valid(
    auth_header_value: str,
    public_key: Certificate,
) -> bool:
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

    if bearer.title() != 'Bearer':
        logger.debug('Malformed Authorization header value: %s', auth_header_value)
        return False

    options = {
        'require': ['exp', 'iat'],
        'verify_exp': 'verify_signature',
    }

    try:
        # This returns the claims as a dictionary, but we aren't using them.  Require the
        # Issued at Time (iat) claim to ensure the JWT varies with each request.  Otherwise,
        # an attacker could replay the static Bearer value.
        jwt.decode(token, public_key, algorithms=['RS256'], options=options)
        return True
    except (jwt.exceptions.InvalidTokenError, TypeError) as e:
        logger.exception(e)

    return False


def make_PUT_request(
    tx_audit_id: str,
    body: dict,
):
    global ssl_context
    assert isinstance(VA_PROFILE_DOMAIN, str), 'What is the domain of the PUT request?'
    assert isinstance(tx_audit_id, str)
    logger.debug('PUT request body: %s', body)

    try:
        # Make a PUT request to VA Profile.
        https_connection = HTTPSConnection(VA_PROFILE_DOMAIN, context=ssl_context)

        https_connection.request(
            'PUT', VA_PROFILE_PATH_BASE + tx_audit_id, json.dumps(body), {'Content-Type': 'application/json'}
        )

        put_response = https_connection.getresponse()

        logger.info('VA Profile responded to the PUT request with HTTP status %d.', put_response.status)
        if put_response.status != 200:
            logger.debug(put_response)
    except ConnectionError as e:
        logger.error('The PUT request to VA Profile failed with a ConnectionError.')
        logger.exception(e)
    except ssl.SSLCertVerificationError as e:
        logger.error('The PUT request to VA Profile failed with a SSLCertVerificationError.')
        logger.debug('Loaded CA certificates: %s', ssl_context.get_ca_certs())
        logger.debug('CA directory contents: %s', os.listdir(CA_PATH))
        logger.exception(e)
    except Exception as e:
        # TODO - Make this more specific.  Is it a timeout?
        logger.error('The PUT request to VA Profile failed.')
        logger.exception(e)
    finally:
        https_connection.close()


def send_comp_and_pen_opt_in_confirmation(va_profile_id: int) -> Optional[HTTPResponse]:
    """
    Send an opt-in confirmation SMS notification based on user's VAProfile ID.

    Args:
        va_profile_id (int): The VA profile ID of the user the notification should be sent to.
    """

    try:
        # Personalization for opt-in confirmation notification SMS based on cutoff date
        # to enroll in monthly Comp and Pen notification
        now = datetime.now(timezone.utc)
        cutoff_datetime = datetime(now.year, now.month, *COMP_AND_PEN_OPT_IN_CUTOFF_TIME_UTC, tzinfo=timezone.utc)

        if now < cutoff_datetime:
            month_personalisation = calendar.month_name[now.month]
        else:
            next_month = (now.month % 12) + 1
            month_personalisation = calendar.month_name[next_month]

        sms_data = json.dumps(
            {
                'template_id': COMP_AND_PEN_OPT_IN_TEMPLATE_ID,
                'recipient_identifier': {'id_type': 'VAPROFILEID', 'id_value': str(va_profile_id)},
                'sms_sender_id': COMP_AND_PEN_SMS_SENDER_ID,
                'personalisation': {'month-name': month_personalisation},
            }
        )

        logger.debug('Sending Comp and Pen opt-in confirmation SMS notification vaProfileId %s', va_profile_id)

        conn = HTTPSConnection(VA_NOTIFY_DOMAIN, context=ssl_context)
        encoded_header = generate_jwt()

        conn.request(
            'POST',
            VA_NOTIFY_SEND_SMS_PATH,
            body=sms_data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {encoded_header}'},
        )

        response = conn.getresponse()

        if response.status != 201:
            logger.error(
                'Failed to send Comp and Pen opt-in confirmation SMS notification. Response status: %s',
                {response.status},
            )
        else:
            return response

    except ValueError as ve:
        logger.exception(
            'Configuration error while attempting to send Comp and Pen opt-in confirmation SMS notification: %s', {ve}
        )

    except Exception as e:
        logger.exception(
            'An error occurred while attempting to send Comp and Pen opt-in confirmation SMS notification to vaProfileId %s: %s',
            va_profile_id,
            e,
        )
    return None


def save_notification_id_to_cache(va_profile_id: int, notification_id: str, source_date: str):
    """
    Update the VAProfileLocalCache table by inserting the notification_id for the given va_profile_id.

    Args:
        va_profile_id (int): The VA profile ID of the user the notification was sent to.
        notification_id (str): The notification UUID.
    """
    try:
        with db_connection.cursor() as cursor:
            # Execute the SQL query with the provided parameters.
            cursor.execute(OPT_IN_OUT_ADD_NOTIFICATION_ID_QUERY, (notification_id, va_profile_id, source_date))

            db_connection.commit()
            logger.info(
                'Successfully updated VAProfileLocalCache with notification_id %s for va_profile_id %s.',
                notification_id,
                va_profile_id,
            )

    except psycopg2.IntegrityError as e:
        db_connection.rollback()
        logger.error(
            'Failed to insert notification_id %s for va_profile_id %s. IntegrityError: %s',
            notification_id,
            va_profile_id,
            str(e),
        )
    except Exception as e:
        db_connection.rollback()
        logger.error(
            'An error occurred while attempting to update notification_id: %s for va_profile_id %s: %s',
            notification_id,
            va_profile_id,
            str(e),
        )
    finally:
        cursor.close()


def generate_jwt() -> str:
    """
    Generate a JWT token for authentication purposes.

    Args:
        service_api_key (str): The API key used to sign the JWT.
        service_id (str): The service identifier.

    Returns:
        str: The generated JWT token.
    """

    headers = {'typ': 'JWT', 'alg': 'HS256'}

    current_timestamp = int(datetime.now().timestamp())
    payload = {'iss': COMP_AND_PEN_SERVICE_ID, 'iat': current_timestamp}

    # Generate and return the signed JWT token using the pyJWT library
    return jwt.encode(payload, COMP_AND_PEN_OPT_IN_API_KEY, algorithm='HS256', headers=headers)


def get_integration_testing_public_cert() -> Certificate:
    """
    Load the integration testing public certificate used to verify JWT signatures for POST requests.
    In deployment environments, the certificate should be available via a lambda layer.  Mock this
    function during unit testing.
    """

    assert NOTIFY_ENVIRONMENT != 'test'

    try:
        with open('/opt/jwt/Notify_integration_testing_public.pem', 'rb') as f:
            return load_pem_x509_certificate(f.read()).public_key()
    except Exception as e:
        logger.exception(e)

    sys.exit('The integration testing public certificate is missing or invalid.  Cannot authenticate POST requests.')

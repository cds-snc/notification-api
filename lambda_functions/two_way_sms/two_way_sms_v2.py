import boto3
import json
import logging
import os
import psycopg2
import requests
import sys

# Constants
AWS_REGION = 'us-gov-west-1'
START_TYPES = ('START', 'BEGIN', 'RESTART', 'OPTIN', 'OPT-IN')
STOP_TYPES = ('STOP', 'OPTOUT', 'OPT-OUT')
HELP_TYPES = ('HELP',)
START_TEXT = 'Message service resumed, reply "STOP" to stop receiving messages.'
STOP_TEXT = 'Message service stopped, reply "START" to start receiving messages.'
HELP_TEXT = 'Some help text'
INBOUND_NUMBERS_QUERY = 'SELECT number, service_id, url_endpoint, self_managed, auth_parameter FROM inbound_numbers;'
SQS_DELAY_SECONDS = 120

# Validation set.  Valid event data must have these attributes.
EXPECTED_PINPOINT_FIELDS = frozenset(('originationNumber', 'destinationNumber', 'messageBody'))

# Environment variables set by the lambda infrastructure
DEAD_LETTER_SQS_URL = os.getenv('DEAD_LETTER_SQS_URL')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
RETRY_SQS_URL = os.getenv('RETRY_SQS_URL')
TIMEOUT = os.getenv('TIMEOUT', '3')

# local variables
client_auth_token = None

if DEAD_LETTER_SQS_URL is None or RETRY_SQS_URL is None:
    sys.exit('A required environment variable is not set.')

logger = logging.getLogger('TwoWaySMSv2')

try:
    logger.setLevel(LOG_LEVEL)
except ValueError:
    logger.setLevel('INFO')
    logger.warning('Invalid log level specified.  Defaulting to INFO.')

try:
    TIMEOUT = tuple(TIMEOUT) if isinstance(TIMEOUT, list) else int(TIMEOUT)
except (TypeError, ValueError):
    TIMEOUT = 3
    logger.warning('Invalid TIMEOUT value specified.  Defaulting to 3 seconds.')


################################################################################################
# Get the database URI from SSM Parameter Store.
################################################################################################
if os.getenv('NOTIFY_ENVIRONMENT') == 'test':
    sqlalchemy_database_uri = os.getenv('SQLALCHEMY_DATABASE_URI')
    client_auth_token = 'test'
else:
    database_uri_path = os.getenv('DATABASE_URI_PATH')
    if database_uri_path is None:
        # Without this value, this code cannot know the path to the required
        # SSM Parameter Store resource.
        sys.exit('DATABASE_URI_PATH is not set.  Check the Lambda console.')

    logger.info('Getting the database URI from SSM Parameter Store . . .')
    ssm_client = boto3.client('ssm', region_name=AWS_REGION)
    ssm_database_uri_path_response: dict = ssm_client.get_parameter(Name=database_uri_path, WithDecryption=True)
    logger.info('. . . Retrieved the database URI from SSM Parameter Store.')
    sqlalchemy_database_uri = ssm_database_uri_path_response.get('Parameter', {}).get('Value')

    if sqlalchemy_database_uri is None:
        sys.exit("Can't get the database URI from SSM Parameter Store.")


def get_ssm_param_info(client_api_auth_ssm_path) -> str:
    ssm_client = boto3.client('ssm', region_name=AWS_REGION)

    # according to the docs you must get a parameter using the name
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm/client/get_parameter.html
    ssm_client_authtoken_path_response: dict = ssm_client.get_parameter(
        Name=client_api_auth_ssm_path, WithDecryption=True
    )
    logger.info('. . . Retrieved the Client AuthToken from SSM Parameter Store.')
    client_auth_token = ssm_client_authtoken_path_response.get('Parameter', {}).get('Value')

    if client_auth_token is None:
        sys.exit("Can't get the Client AuthToken from SSM Param Store")

    return client_auth_token


if os.getenv('NOTIFY_ENVIRONMENT') == 'test':
    two_way_sms_table_dict = {}
else:
    db_connection = None
    try:
        logger.info('Retrieving the 10DLC-to-URL mapping from the database . . .')
        db_connection = psycopg2.connect(sqlalchemy_database_uri)
        if db_connection is None:
            sys.exit('No database connection.')

        with db_connection.cursor() as c:
            # https://www.psycopg.org/docs/cursor.html#cursor.execute
            c.execute(INBOUND_NUMBERS_QUERY)
            mapping_data = c.fetchall()
            logger.debug('Data returned from query: %s', mapping_data)

        logger.info('. . . Retrieved the 10DLC-to-URL mapping from the database.')
    except psycopg2.Warning as e:
        logger.warning(e)
    except psycopg2.OperationalError as e:
        # This exception is raised if a database connection is not established.
        logger.exception(e)
        sys.exit('Unable to retrieve the 10DLC-to-URL mapping from the database.')
    finally:
        if db_connection is not None and not db_connection.closed:
            db_connection.close()

    # Create the mapping table with a generator expression.
    two_way_sms_table_dict = {
        n: {
            'service_id': s,
            'url_endpoint': u,
            'self_managed': sm,
            'auth_parameter': ap,
        }
        for n, s, u, sm, ap in mapping_data
    }

logger.debug('10DLC-to-URL mapping: %s', two_way_sms_table_dict)

################################################################################################
# Above, use the database URI to get a 10DLC-to-URL mapping from the database.
# The format should be:
#    {
#        <phone number>: {
#            'service_id': <value>,
#            'url_endpoint': <value>,
#            'self_managed': <value>,
#            'auth_parameter': <value>,
#        }
#    }
################################################################################################


aws_sqs_client = boto3.client('sqs', region_name=AWS_REGION)


# ------------------------------------------- Begin Invocation --------------------------------------------
def notify_incoming_sms_handler(
    event: dict,
    context: any,
):
    """
    Handler for inbound messages from SQS.
    """

    logger.debug('Event: %s', event)
    batch_item_failures = []

    if not valid_event(event):
        logger.error('Invalid event: %s', event)

        # Push the message to the dead letter queue, and return 200 to have the message removed from feeder queue.
        push_to_sqs(event, False)
        return create_response(200)

    # SQS events should contain "Records", and each record should contain "body".
    # This is checked in the call above to valid_event.
    for record in event['Records']:
        # The body should be stringified JSON.
        record_body = record['body']

        try:
            record_body = json.loads(record_body)
            inbound_sms = json.loads(record_body.get('Message'))
        except (json.decoder.JSONDecodeError, TypeError) as e:
            # Dead letter
            logger.exception(e)
            logger.error('Malformed record body: %s', record_body)
            push_to_sqs(record_body, False)
            continue

        if not valid_message_body(inbound_sms):
            logger.error("The record's message body is invalid: %s", inbound_sms)

            # Push the record to the dead letter queue, and return 200 to have the message removed from the feeder queue
            push_to_sqs(record_body, False)
            if len(event['Records']) > 1:
                logger.warning('Multiple records might not be processed correctly unless batching is implemented.')
            return create_response(200)
        # Else, the message has all the required fields.

        # destinationNumber is the 10DLC Pinpoint number to which the end user responded.
        two_way_record = two_way_sms_table_dict.get(inbound_sms['destinationNumber'])
        if two_way_record is None:
            # Dead letter
            logger.error('Unable to find a two_way_record for %s.', inbound_sms.get('destinationNumber', 'unknown'))
            push_to_sqs(record_body, False)
            continue

        # Forward inbound_sms to the associated service.
        logger.info(
            'POSTing the inbound SMS to service: %s. UrlEndpoint: %s. Destination number: %s',
            two_way_record.get('service_id', 'unknown'),
            two_way_record.get('url_endpoint', 'unknown'),
            inbound_sms.get('destinationNumber', 'unknown'),
        )

        try:
            result_of_forwarding = forward_to_service(
                inbound_sms, two_way_record.get('url_endpoint'), two_way_record.get('auth_parameter')
            )
        except Exception:
            # Dead letter.  This exception was re-raised and has already been logged.
            push_to_sqs(record_body, False)
            continue

        if not result_of_forwarding:
            logger.warning('Failed to make an HTTP request. Placing the record in the retry queue.')
            batch_item_failures.append({'itemIdentifier': record_body.get('messageId', '')})
            push_to_sqs(record_body, True)

    # Return an array of message Ids that failed so that they get re-enqueued.
    return {
        'data': batch_item_failures,
        'statusCode': 400 if batch_item_failures else 200,
    }


def create_response(status_code: int):
    """
    Create a response object to return after the lambda completes processing.
    """

    return {'statusCode': status_code, 'isBase64Encoded': False, 'body': 'Success' if status_code == 200 else 'Failure'}


def valid_message_body(inbound_sms: dict) -> bool:
    """
    Return a boolean to indicate if a record body's message contains
    all required attributes.
    """

    return EXPECTED_PINPOINT_FIELDS.issubset(inbound_sms)


def valid_event(event_data: dict) -> bool:
    """
    Ensure the event data has a "Records" list of objects and that each record
    object has a "body" attribute.
    """

    if event_data is None or 'Records' not in event_data:
        return False

    return all((record.get('body') is not None) for record in event_data['Records'])


def forward_to_service(
    inbound_sms: dict,
    url: str,
    auth_parameter: str,
) -> bool:
    """
    Forwards the inbound SMS to the service that has 2-way SMS setup.
    """

    global client_auth_token

    if client_auth_token != 'test':
        try:
            client_auth_token = get_ssm_param_info(client_api_auth_ssm_path=auth_parameter)
        except Exception as e:
            logger.exception('Issue attempting to get ssm parameter for incoming two-way sms - Exception: %s', e)

        if client_auth_token is None:
            logger.critical(
                'Raising execption because client_auth_token could not be retrieved from SSM. client_auth_token = %s',
                client_auth_token,
            )
            raise Exception('Raising exception because client_auth_token could not be retrieved from SSM.')

    # This covers None and the empty string.
    if not url:
        logger.error('No URL provided in the configuration for the service.')
        return False

    headers = {'Content-type': 'application/json', 'Authorization': 'Basic ' + client_auth_token}

    try:
        response = requests.post(
            url,
            verify=False if 'vetext' in auth_parameter else True,
            json=inbound_sms,
            timeout=TIMEOUT,
            headers=headers,
        )
        logger.info('The POST to the service is complete.')
        response.raise_for_status()

        logger.info('Response Status: %d', response.status_code)
        logger.debug('Response Content: %s', response.content)
        return True
    except (requests.HTTPError, requests.RequestException) as e:
        logger.warning('Forward request failed - Retryable. Error: %s', e)
    except Exception as e:
        logger.critical(
            'Unexpected Exception forwarding to url: %s, with message: %s, and error: %s',
            url,
            inbound_sms,
            e,
        )

        # Re-raise to move the message to the dead letter queue instead of the retry queue.
        raise

    return False


def push_to_sqs(
    push_data: dict,
    is_retry: bool,
) -> None:
    """
    Pushes an inbound sms or entire event to SQS. Sends to RETRY or DEAD LETTER queue dependent
    on is_retry variable.
    """

    logger.warning('Pushing to the %s queue . . .', 'RETRY' if is_retry else 'DEAD LETTER')
    logger.debug('SQS push data of type %s: %s', type(push_data), push_data)

    try:
        queue_msg = json.dumps(push_data)
    except TypeError as e:
        # Unable enqueue the data in any queue.  Don't try sending it to the dead letter queue.
        logger.exception(e)
        logger.critical('. . . The data is being dropped: %s', push_data)
        return

    # NOTE: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_SendMessage.html
    # Need to ensure none of those unicode characters are in the message or it's gone.
    try:
        aws_sqs_client.send_message(
            QueueUrl=RETRY_SQS_URL if is_retry else DEAD_LETTER_SQS_URL,
            MessageBody=queue_msg,
            DelaySeconds=SQS_DELAY_SECONDS,
        )

        logger.warning('. . . Completed the SQS push.')
    except Exception as e:
        logger.exception(e)
        logger.critical('. . . Failed to push to SQS with data: %s', push_data)

        if is_retry:
            # Retry failed.  Push to the dead letter queue.
            push_to_sqs(push_data, False)
        else:
            # The dead letter queue failed.
            logger.critical('The data is being dropped.')

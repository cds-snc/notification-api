import boto3
import json
import logging
import os
import psycopg2
import requests
import sys
from datetime import datetime

# Constants
AWS_REGION = "us-gov-west-1"
START_TYPES = ('START', 'BEGIN', 'RESTART', 'OPTIN', 'OPT-IN')
STOP_TYPES = ('STOP', 'OPTOUT', 'OPT-OUT')
HELP_TYPES = ('HELP',)
START_TEXT = 'Message service resumed, reply "STOP" to stop receiving messages.'
STOP_TEXT = 'Message service stopped, reply "START" to start receiving messages.'
HELP_TEXT = 'Some help text'
INBOUND_NUMBERS_QUERY = """SELECT number, service_id, url_endpoint, self_managed FROM inbound_numbers;"""
SQS_DELAY_SECONDS = 120

# Validation set.  Valid event data must have these attributes.
EXPECTED_PINPOINT_FIELDS = frozenset(('originationNumber', 'destinationNumber', 'messageBody'))

# Environment variables set by the lambda infrastructure
# TODO - Uncomment this line when the code commented-out at the end is restored.
# AWS_PINPOINT_APP_ID = os.getenv("AWS_PINPOINT_APP_ID")
DEAD_LETTER_SQS_URL = os.getenv("DEAD_LETTER_SQS_URL")
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
RETRY_SQS_URL = os.getenv('RETRY_SQS_URL')
TIMEOUT = os.getenv('TIMEOUT', '3')
VETEXT_API_AUTH_SSM_PATH = os.getenv('VETEXT_API_AUTH_SSM_PATH')

if (
    # TODO - Uncomment this line when the code commented-out at the end is restored.
    # AWS_PINPOINT_APP_ID is None or
    DEAD_LETTER_SQS_URL is None or
    RETRY_SQS_URL is None or
    VETEXT_API_AUTH_SSM_PATH is None
):
    sys.exit("A required environment variable is not set.")

logger = logging.getLogger('TwoWaySMSv2')

try:
    logger.setLevel(LOG_LEVEL)
except ValueError:
    logger.setLevel("INFO")
    logger.warning("Invalid log level specified.  Defaulting to INFO.")

try:
    TIMEOUT = tuple(TIMEOUT) if isinstance(TIMEOUT, list) else int(TIMEOUT)
except (TypeError, ValueError):
    TIMEOUT = 3
    logger.warning("Invalid TIMEOUT value specified.  Defaulting to 3 seconds.")


################################################################################################
# Get the database URI from SSM Parameter Store.
################################################################################################

if os.getenv("NOTIFY_ENVIRONMENT") == "test":
    sqlalchemy_database_uri = os.getenv("SQLALCHEMY_DATABASE_URI")
    vetext_auth_token = os.getenv("VETEXT_API_AUTH_SSM_PATH")
else:
    database_uri_path = os.getenv("DATABASE_URI_PATH")
    if database_uri_path is None:
        # Without this value, this code cannot know the path to the required
        # SSM Parameter Store resource.
        sys.exit("DATABASE_URI_PATH is not set.  Check the Lambda console.")

    logger.info("Getting the database URI from SSM Parameter Store . . .")
    ssm_client = boto3.client("ssm", region_name=AWS_REGION)
    ssm_database_uri_path_response: dict = ssm_client.get_parameter(
        Name=database_uri_path,
        WithDecryption=True
    )
    logger.info(". . . Retrieved the database URI from SSM Parameter Store.")
    sqlalchemy_database_uri = ssm_database_uri_path_response.get("Parameter", {}).get("Value")

    if sqlalchemy_database_uri is None:
        sys.exit("Can't get the database URI from SSM Parameter Store.")

    ssm_vetext_authtoken_path_response: dict = ssm_client.get_parameter(
        Name=VETEXT_API_AUTH_SSM_PATH,
        WithDecryption=True
    )
    logger.info(". . . Retrieved the VeText AuthToken from SSM Parameter Store.")
    vetext_auth_token = ssm_vetext_authtoken_path_response.get("Parameter", {}).get("Value")

    if vetext_auth_token is None:
        sys.exit("Can't get the VeText AuthToken from SSM Param Store")

################################################################################################
# Use the database URI to get a 10DLC-to-URL mapping from the database.
# The format should be:
#    {
#        <phone number>: {
#            'service_id': <value>,
#            'url_endpoint': <value>,
#            'self_managed': <value>,
#        }
#    }
################################################################################################

if os.getenv("NOTIFY_ENVIRONMENT") == "test":
    two_way_sms_table_dict = {}
else:
    db_connection = None
    try:
        logger.info("Retrieving the 10DLC-to-URL mapping from the database . . .")
        db_connection = psycopg2.connect(sqlalchemy_database_uri)
        if db_connection is None:
            sys.exit("No database connection.")

        with db_connection.cursor() as c:
            # https://www.psycopg.org/docs/cursor.html#cursor.execute
            c.execute(INBOUND_NUMBERS_QUERY)
            mapping_data = c.fetchall()
            logger.debug("Data returned from query: %s", mapping_data)

        logger.info(". . . Retrieved the 10DLC-to-URL mapping from the database.")
    except psycopg2.Warning as e:
        logger.warning(e)
    except psycopg2.OperationalError as e:
        # This exception is raised if a database connection is not established.
        logger.exception(e)
        sys.exit("Unable to retrieve the 10DLC-to-URL mapping from the database.")
    finally:
        if db_connection is not None and not db_connection.closed:
            db_connection.close()

    # Create the mapping table with a generator expression.
    two_way_sms_table_dict = {
        n: {
            'service_id': s,
            'url_endpoint': u,
            'self_managed': sm,
        } for n, s, u, sm in mapping_data
    }

logger.debug('10DLC-to-URL mapping: %s', two_way_sms_table_dict)

################################################################################################

# TODO - Uncomment this line when the code commented-out at the end is restored.
# aws_pinpoint_client = boto3.client('pinpoint', region_name=AWS_REGION)
aws_sqs_client = boto3.client('sqs', region_name=AWS_REGION)


# ------------------------------------------- Begin Invocation --------------------------------------------
def notify_incoming_sms_handler(event: dict, context: any):
    """
    Handler for inbound messages from SQS.
    """

    logger.debug("Event: %s", event)
    batch_item_failures = []

    if not valid_event(event):
        logger.error("Invalid event: %s", event)

        # Push the message to the dead letter queue, and return 200 to have the message removed from feeder queue.
        push_to_sqs(event, False)
        return create_response(200)

    # SQS events should contain "Records", and each record should contain "body".
    # This is checked in the call above to valid_event.
    for record in event["Records"]:
        # The body should be stringified JSON.
        record_body = record["body"]

        try:
            record_body = json.loads(record_body)
            inbound_sms = json.loads(record_body.get("Message"))
        except (json.decoder.JSONDecodeError, TypeError) as e:
            # Dead letter
            logger.exception(e)
            logger.error("Malformed record body: %s", record_body)
            push_to_sqs(record_body, False)
            continue

        if not valid_message_body(inbound_sms):
            logger.error("The record's message body is invalid: %s", inbound_sms)

            # Push the record to the dead letter queue, and return 200 to have the message removed from the feeder queue.
            push_to_sqs(record_body, False)
            if len(event["Records"]) > 1:
                # TODO - Remove this block as part of #1014.  The problem is that the handler returns if any record has
                # an invalid message.  It's not a problem now because we only expect one record.
                logger.warning("Multiple records might not be processed correctly until batching is implemented.  See #1014.")
            return create_response(200)
        # Else, the message has all the required fields.

        # destinationNumber is the 10DLC Pinpoint number to which the end user responded.
        two_way_record = two_way_sms_table_dict.get(inbound_sms["destinationNumber"])
        if two_way_record is None:
            # Dead letter
            logger.error("Unable to find a two_way_record for %s.", inbound_sms.get("destinationNumber", "unknown"))
            push_to_sqs(record_body, False)
            continue

        # **Note** - Commenting out this code for self managed checking because right now we are relying on AWS to manage opt out/in functionality.  
        # **Note** - Eventually we will migrate to self-managed for everything and the config determination will be whether Notify is handling the functionality or if the business line is
        # If the number is not self-managed, look for key words
        #if not two_way_record.get('self_managed'):
        #    logger.info('Service is not self-managed')
        #    keyword_phrase = detected_keyword(inbound_sms["messageBody"])
        #    if keyword_phrase:
        #        # originationNumber is the veteran number.
        #        send_message(two_way_record.get('originationNumber', ''),
        #                     two_way_record.get('destinationNumber', ''),
        #                     keyword_phrase)

        # Forward inbound_sms to the associated service.
        logger.info(
            "POSTing the inbound SMS to service: %s. UrlEndpoint: %s. Destination number: %s",
            two_way_record.get("service_id", "unknown"),
            two_way_record.get("url_endpoint", "unknown"),
            inbound_sms.get("destinationNumber", "unknown")
        )

        try:
            result_of_forwarding = forward_to_service(inbound_sms, two_way_record.get("url_endpoint"))
        except Exception as e:
            # Dead letter.  This exception was re-raised and has already been logged.
            push_to_sqs(record_body, False)
            continue

        if not result_of_forwarding:
            logger.error("Failed to make an HTTP request.  Placing the record in the retry queue.")
            batch_item_failures.append({"itemIdentifier": record_body.get("messageId", '')})
            push_to_sqs(record_body, True)

    # Return an array of message Ids that failed so that they get re-enqueued.
    return {
        "data": batch_item_failures,
        "statusCode": 400 if batch_item_failures else 200,
    }


def create_response(status_code: int):
    """
    Create a response object to return after the lambda completes processing.
    """

    return {
        "statusCode": status_code,
        "isBase64Encoded": False,
        "body": "Success" if status_code == 200 else "Failure"
    }


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

    if event_data is None or "Records" not in event_data:
        return False

    return all((record.get("body") is not None) for record in event_data["Records"])


def forward_to_service(inbound_sms: dict, url: str) -> bool:
    """
    Forwards the inbound SMS to the service that has 2-way SMS setup.
    """

    # This covers None and the empty string.
    if not url:
        logger.error("No URL provided in the configuration for the service.")
        return False

    headers = {
        'Content-type': 'application/json',
        'Authorization': 'Basic ' + vetext_auth_token
    }

    try:
        response = requests.post(
            url,            
            verify=False,
            json=inbound_sms,
            timeout=TIMEOUT,
            headers=headers
        )
        logger.info("The POST to the service is complete.")
        response.raise_for_status()

        logger.info('Response Status: %d', response.status_code)
        logger.debug('Response Content: %s', response.content)
        return True
    except (requests.HTTPError, requests.RequestException) as e:
        logger.exception(e)
    except Exception as e:
        logger.exception(e)
        logger.critical("General Exception With Http Request.  The record should go to the dead letter queue.")

        # Re-raise to move the message to the dead letter queue instead of the retry queue.
        raise

    return False


def push_to_sqs(push_data: dict, is_retry: bool) -> None:
    """
    Pushes an inbound sms or entire event to SQS. Sends to RETRY or DEAD LETTER queue dependent
    on is_retry variable. 
    """

    logger.warning("Pushing to the %s queue . . .", "RETRY" if is_retry else "DEAD LETTER")
    logger.debug("SQS push data of type %s: %s", type(push_data), push_data)

    try:
        queue_msg = json.dumps(push_data)
    except TypeError as e:
        # Unable enqueue the data in any queue.  Don't try sending it to the dead letter queue.
        logger.exception(e)
        logger.critical(". . . The data is being dropped: %s", push_data)
        return

    # NOTE: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_SendMessage.html
    # Need to ensure none of those unicode characters are in the message or it's gone.
    try:
        aws_sqs_client.send_message(
            QueueUrl=RETRY_SQS_URL if is_retry else DEAD_LETTER_SQS_URL,
            MessageBody=queue_msg,
            DelaySeconds=SQS_DELAY_SECONDS
        )

        logger.warning(". . . Completed the SQS push.")
    except Exception as e:
        logger.exception(e)
        logger.critical(". . . Failed to push to SQS with data: %s", push_data)

        if is_retry:
            # Retry failed.  Push to the dead letter queue.
            push_to_sqs(push_data, False)
        else:
            # The dead letter queue failed.
            logger.critical("The data is being dropped.")


# **Note** - Commented out because it wont be necessary in this initial release
#def detected_keyword(message: str) -> str:
#    """
#    Parses the string to look for start, stop, or help key words and handles those.
#    """

#    message = message.upper()
#    if message.startswith(START_TYPES):
#        logger.info('Detected a START_TYPE keyword')
#        return START_TEXT
#    elif message.startswith(STOP_TYPES):
#        logger.info('Detected a STOP_TYPE keyword')
#        return STOP_TEXT
#    elif message.startswith(HELP_TEXT):
#        logger.info('Detected a HELP_TYPE keyword')
#        return HELP_TEXT
#    else:
#        logger.info('No keywords detected...')
#        return ''

# **Note** - Commented out because it wont be necessary in this initial release
#def send_message(recipient_number: str, sender: str, message: str) -> dict:
#    """
#    Called when we are monitoring for keywords and one was detected. This sends the 
#    appropriate response to the phone number that requested a message via keyword.
#    """
#    try:
#        # Should probably be smsv2
#        response = aws_pinpoint_client.send_messages(
#            ApplicationId=AWS_PINPOINT_APP_ID,
#            MessageRequest={'Addresses': {recipient_number: {'ChannelType': 'SMS'}},
#                            'MessageConfiguration': {'SMSMessage': {'Body': message,
#                                                                    'MessageType': 'TRANSACTIONAL',
#                                                                    'OriginationNumber': sender}}}
#        )
#        aws_reference = response['MessageResponse']['Result'][recipient_number]['MessageId']
#        logging.info('Message sent, reference: %s', aws_reference)
#    except Exception as e:
#        logger.critical('Failed to send message: %s to %s from %s', message, recipient_number, sender)
#        logger.exception(e)

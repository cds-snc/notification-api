"""This module is used to transfer incoming twilio requests to a Vetext endpoint."""

import base64
from copy import deepcopy
from cryptography.fernet import Fernet, MultiFernet
import json
import logging
import os
import sys
from typing import Optional
from functools import lru_cache
from urllib.parse import parse_qsl, parse_qs

import boto3
import requests
from twilio.request_validator import RequestValidator

logger = logging.getLogger('vetext_incoming_forwarder_lambda')

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
try:
    logger.setLevel(LOG_LEVEL)
except ValueError:
    logger.setLevel('INFO')
    logger.exception('Invalid log level specified.  Defaulting to INFO.')

# http timeout for calling vetext endpoint
HTTPTIMEOUT = (3.05, 1)

TWILIO_AUTH_TOKEN_SSM_NAME = os.getenv('TWILIO_AUTH_TOKEN_SSM_NAME')
TWILIO_PH_AUTH_TOKEN_SSM_NAME = os.getenv('TWILIO_PH_AUTH_TOKEN_SSM_NAME')
LOG_ENCRYPTION_SSM_NAME = os.getenv('LOG_ENCRYPTION_SSM_NAME')

if TWILIO_AUTH_TOKEN_SSM_NAME is None or TWILIO_AUTH_TOKEN_SSM_NAME == 'DEFAULT' or LOG_ENCRYPTION_SSM_NAME is None:  # nosec
    sys.exit('A required environment variable is not set. Please ensure all env variables are set')

TWILIO_VETEXT_PATH = '/twoway/vettext'
TWILIO_VETEXT2_PATH = '/twoway/vetext2'


def get_ssm_params(params):
    """Collects parameter(s) depending on params passed in

    Args:
        params (Union[list[str], str]): parameter names
    Returns:
        Union[list[str], str]: The value(s) of the given parameter(s)
    """
    try:
        ssm_client = boto3.client('ssm')
        if isinstance(params, list):
            response = ssm_client.get_parameters(
                Names=params,
                WithDecryption=True,
            )
            params_value = [parameter['Value'] for parameter in response['Parameters']]
        else:
            response = ssm_client.get_parameter(
                Name=params,
                WithDecryption=True,
            )
            params_value = response['Parameter']['Value']
    except Exception:
        logger.exception('Failed to get the value for parameter %s.', params)
        sys.exit('Unable to retrieve parameter store value.  Exiting.')

    return params_value


def get_twilio_tokens():
    """
    Is run during execution environment setup.
    @return: List of Twilio auth tokens from SSM
    """
    try:
        if TWILIO_AUTH_TOKEN_SSM_NAME == 'unit_test' or TWILIO_PH_AUTH_TOKEN_SSM_NAME == 'unit_test':  # nosec
            # item 0 was the auth token used to sign the body of the request
            return ['bad_twilio_auth', 'invalid_auth', 'unit_test']

        return get_ssm_params([TWILIO_AUTH_TOKEN_SSM_NAME, TWILIO_PH_AUTH_TOKEN_SSM_NAME])
    except Exception:
        logger.exception('Failed to retrieve required paramaters from SSM.')
        sys.exit('Unable to retrieve required auth token(s).  Exiting.')


def get_encryption() -> MultiFernet:
    """Collects the log encryption key(s) and sets up the MultiFernet used for log encryption"""
    if LOG_ENCRYPTION_SSM_NAME == 'fake_value':
        return MultiFernet([Fernet(Fernet.generate_key()), Fernet(Fernet.generate_key())])
    try:
        encryption_log_key_str = get_ssm_params(LOG_ENCRYPTION_SSM_NAME)
        # Clear spaces and split on commas
        key_list = encryption_log_key_str.replace(' ', '').split(',')
        # MultiFernet uses the first key, then tries subsequent, allows for rotation
        multifernet = MultiFernet([Fernet(key.encode()) for key in key_list])
    except Exception:
        logger.exception('Failed to set encryption key for failed validation logging.')
        sys.exit('Unable to retrieve/set required encryption keys, exiting')

    return multifernet


auth_tokens = get_twilio_tokens()
encryption = get_encryption()


def validate_twilio_event(event: dict) -> bool:
    """
    Defined both here and in delivery_status_processor.
    Validates that event was from Twilio.
    @param: event
    @return: bool
    """
    logger.info('validating twilio vetext forwarder event')

    try:
        signature = event['headers'].get('x-twilio-signature', '')
        if not auth_tokens or not signature:
            logger.error('Twilio auth token(s) or signature not set.')
            return False
        validators = [RequestValidator(auth_token) for auth_token in auth_tokens]
        uri = f"https://{event['headers']['host']}/vanotify{event['path']}"

        decoded = base64.b64decode(event.get('body')).decode('utf-8')
        params = parse_qs(decoded, keep_blank_values=True)
        params = {k: v[0] for k, v in params.items()}
        return any([validator.validate(uri=uri, params=params, signature=signature) for validator in validators])
    except Exception:
        logger.exception('Error validating the request origin.')
        return False


def vetext_incoming_forwarder_lambda_handler(
    event: dict,
    context: any,
):
    """this method takes in an event passed in by either an alb or sqs.
    @param: event   -  contains data pertaining to an incoming sms from Twilio
    @param: context -  contains information regarding information
        regarding what triggered the lambda (context.invoked_function_arn).
    """
    try:
        logger.debug('Entrypoint event: %s', event)
        logger.debug('Context: %s', context)

        # Determine if the invoker of the lambda is SQS or ALB
        #   SQS will submit batches of records so there is potential for multiple events to be processed
        #   ALB will submit a single request but to simplify code, it will also return an array of event bodies
        if 'requestContext' in event and 'elb' in event['requestContext']:
            logger.info('alb invocation')
            # The check for context is to allow for local testing. While context is always present when deployed,
            # setting it False locally allows for testing without a valid Twilio signature.
            if context and not validate_twilio_event(event):
                try:
                    logger.info(
                        'Returning 403 on unauthenticated Twilio request for event: %s',
                        encryption.encrypt(json.dumps(event).encode()).decode(),
                    )
                except Exception:
                    # In the event encryption or the dump fails, still log the event.
                    logger.exception(
                        'Returning 403 on unauthenticated Twilio request for event: %s - Unable to encrypt/json dump',
                        event,
                    )
                return create_twilio_response(403)
            logger.info('Authenticated Twilio request')
            event_bodies = process_body_from_alb_invocation(event)
        elif 'Records' in event:
            logger.info('sqs invocation')
            event_bodies = process_body_from_sqs_invocation(event)
        else:
            logger.error(
                'Invalid Event. Expecting the source of an invocation to be from alb or sqs. Received: %s', event
            )
            push_to_dead_letter_sqs(event, 'vetext_incoming_forwarder_lambda_handler')

            return create_twilio_response(500)

        logger.debug('Successfully processed event to event_bodies. Received: %s', event_bodies)

        for event_body in event_bodies:
            logger.debug('Processing event_body: %s', event_body)
            logger.info('Processing MessageSid: %s', event_body.get('MessageSid'))
            # We cannot currently handle audio, images, etc. Only forward if it has a Body field
            if not event_body.get('Body'):
                redacted_event = deepcopy(event_body)
                redacted_event['From'] = 'redacted'
                logger.warning('Event was missing a body: %s', redacted_event)
                continue
            response = make_vetext_request(event_body)

            if response is None:
                push_to_retry_sqs(event_body)

        return create_twilio_response()
    except Exception:
        logger.exception('Unexpected exception')
        push_to_dead_letter_sqs(event, 'vetext_incoming_forwarder_lambda_handler')

        return create_twilio_response(500)


def create_twilio_response(status_code: int = 200):
    response = {'headers': {'Content-Type': 'text/xml'}, 'body': '<Response />', 'statusCode': status_code}

    return response


def process_body_from_sqs_invocation(event):
    event_bodies = []
    for record in event['Records']:
        # record is a sqs event that contains a body
        # body is an alb request that failed in an initial request
        # event is a json document with a body attribute that contains
        #   the payload of the twilio webhook
        # event["body"] is a base 64 encoded string
        # parse_qsl converts url-encoded strings to array of tuple objects
        # event_body takes the array of tuples and creates a dictionary
        event_body = None
        try:
            event_body = record.get('body', '')

            if not event_body:
                logger.info('event_body from sqs record was not present')
                logger.debug('Record: %s', record)
                continue

            logger.debug('Processing record body from SQS.')
            if not isinstance(event_body, dict):
                event_body = json.loads(event_body)
                logger.info('Successfully converted record body from sqs to json.')
            event_bodies.append(event_body)
        except json.decoder.JSONDecodeError:
            logger.exception('Failed to load json event_body.')
            push_to_dead_letter_sqs(event_body, 'process_body_from_sqs_invocation')
        except Exception:
            logger.exception('Failed to load the event from sqs.')
            push_to_dead_letter_sqs(event_body, 'process_body_from_sqs_invocation')

    return event_bodies


def process_body_from_alb_invocation(event):
    # event is a json document with a body attribute that contains
    #   the payload of the twilio webhook
    # event["body"] is a base 64 encoded string
    # parse_qsl converts url-encoded strings to array of tuple objects
    # event_body takes the array of tuples and creates a dictionary
    event_body_encoded = event.get('body', '')
    event_path = event.get('path', '')

    if not event_body_encoded:
        logger.error('event_body from alb record was not present: %s', event)

    if not event_path:
        logger.error('event_path from alb record was not present: %s', event)

    event_body_decoded = parse_qsl(base64.b64decode(event_body_encoded).decode('utf-8'))
    logger.debug('Decoded event body: %s', event_body_decoded)
    logger.debug('Event path: %s', event_path)

    event_body = dict(event_body_decoded)
    logger.debug('Converted body to dictionary: %s', event_body)

    if 'AddOns' in event_body:
        logger.debug('AddOns present in event_body: %s', event_body['AddOns'])
        del event_body['AddOns']

    # Add the path to the event body, for routing purposes
    event_body['path'] = event_path
    return [event_body]


@lru_cache(maxsize=None)
def read_from_ssm(key: str) -> str:
    ssm_client = boto3.client('ssm')
    logger.info('Getting key: %s from SSM', key)
    try:
        response = ssm_client.get_parameter(Name=key, WithDecryption=True)
        logger.info('received ssm parameter')
    except Exception as e:
        logger.critical('Exception raised while looking up SSM key %s. Exception: %s', key, e)
        response = {}

    return response.get('Parameter', {}).get('Value')


def make_vetext_request(request_body):  # noqa: C901 (too complex 13 > 10)
    endpoint = request_body.get('path', TWILIO_VETEXT_PATH)
    logger.debug('Making VeText Request for endpoint: %s', endpoint)

    if endpoint == TWILIO_VETEXT_PATH:
        ssm_path = os.getenv('vetext_api_auth_ssm_path')
        if ssm_path is None:
            logger.error('Unable to retrieve vetext_api_auth_ssm_path from env variables')
            return

        domain = os.getenv('vetext_api_endpoint_domain')
        if domain is None:
            logger.error('Unable to retrieve vetext_api_endpoint_domain from env variables')
            return

        path = os.getenv('vetext_api_endpoint_path')
        if path is None:
            logger.error('Unable to retrieve vetext_api_endpoint_path from env variables')
            return

    elif endpoint == TWILIO_VETEXT2_PATH:
        ssm_path = os.getenv('VETEXT2_BASIC_AUTH_SSM_PATH')
        if ssm_path is None:
            logger.error('Unable to retrieve vetext_api_auth_ssm_path from env variables')
            return

        domain = os.getenv('VETEXT2_API_ENDPOINT_DOMAIN')
        if domain is None:
            logger.error('Unable to retrieve vetext_api_endpoint_domain from env variables')
            return

        path = os.getenv('VETEXT2_API_ENDPOINT_PATH')
        if path is None:
            logger.error('Unable to retrieve vetext_api_endpoint_path from env variables')
            return
    else:
        logger.error('Invalid endpoint: %s', endpoint)
        return

    # Authorization is basic token authentication that is stored in environment.
    auth_token: Optional[str] = read_from_ssm(ssm_path)

    if not auth_token:
        logger.error('Unable to retrieve auth token from SSM')
        return

    headers = {'Content-type': 'application/json', 'Authorization': 'Basic ' + auth_token}

    body = {
        'accountSid': request_body.get('AccountSid', ''),
        'messageSid': request_body.get('MessageSid', ''),
        'messagingServiceSid': request_body.get('MessagingServiceSid', ''),
        'to': request_body.get('To', ''),
        'from': request_body.get('From', ''),
        'messageStatus': request_body.get('SmsStatus', ''),
        'body': request_body.get('Body', ''),
    }

    endpoint_uri = f'https://{domain}{path}'

    logger.info('Making POST Request to VeText using URL endpoint: %s, To: %s', endpoint_uri, body['to'])
    logger.debug('json dumps: %s', json.dumps(body))
    response = None

    try:
        response = requests.post(endpoint_uri, verify=False, json=body, timeout=HTTPTIMEOUT, headers=headers)  # nosec
        logger.info('VeText POST complete')
        response.raise_for_status()

        logger.info('VeText call complete with response: %d', response.status_code)
        logger.debug('VeText response: %s', response.content)
        return response.content
    except requests.HTTPError as e:
        logged_body = body.copy()
        logged_body['body'] = 'redacted'
        logger.warning(
            'HTTPError With Call To VeText url: %s, with body: %s, response: %s, and error: %s',
            endpoint_uri,
            logged_body,
            getattr(response, 'content', 'none'),
            e,
        )
    except requests.RequestException as e:
        logged_body = body.copy()
        logged_body['body'] = 'redacted'
        logger.warning(
            'RequestException With Call To VeText url: %s, with body: %s, response: %s, and error: %s',
            endpoint_uri,
            logged_body,
            getattr(response, 'content', 'none'),
            e,
        )
    except Exception:
        logged_body = body.copy()
        logged_body['body'] = 'redacted'
        logger.exception(
            'Unexpected Exception With Call to VeText url: %s, with body: %s, and response %s',
            endpoint_uri,
            logged_body,
            getattr(response, 'content', 'none'),
        )

    return None


def push_to_retry_sqs(event_body):
    """Places event body dictionary on queue to be retried at a later time"""
    logger.info('Placing event_body on retry queue')
    logger.debug('Preparing for Retry SQS: %s', event_body)

    queue_url = os.getenv('vetext_request_drop_sqs_url')

    if queue_url is None:
        logger.error('Unable to retrieve vetext_request_drop_sqs_url from env variables for event: %s', event_body)
        return None

    logger.debug('Retrieved queue_url: %s', queue_url)

    try:
        sqs = boto3.client('sqs')

        queue_msg = json.dumps(event_body)
        queue_msg_attrs = {'source': {'DataType': 'String', 'StringValue': 'twilio'}}

        sqs.send_message(QueueUrl=queue_url, MessageAttributes=queue_msg_attrs, MessageBody=queue_msg)

        logger.info('Completed enqueue of message to retry queue')
    except Exception:
        logger.exception('Push to Retry SQS Exception for event: %s', event_body)
        push_to_dead_letter_sqs(event_body, 'push_to_retry_sqs')


def push_to_dead_letter_sqs(
    event,
    source,
):
    """Places unaccounted for event on dead-letter queue to be inspected"""

    logger.info('Preparing for DeadLetter SQS: %s', event)

    queue_url = os.getenv('vetext_request_dead_letter_sqs_url')

    if queue_url is None:
        logger.error('Unable to retrieve vetext_request_dead_letter_sqs_url from env variables for event: %s', event)
        return None

    logger.debug('Retrieved queue_url: %s', queue_url)

    try:
        sqs = boto3.client('sqs')

        queue_msg = json.dumps(event)
        queue_msg_attrs = {'source': {'DataType': 'String', 'StringValue': source}}

        sqs.send_message(QueueUrl=queue_url, MessageAttributes=queue_msg_attrs, MessageBody=queue_msg)

        logger.info('Completed enqueue of message to dead letter queue')
    except Exception:
        logger.exception('Push to Dead Letter SQS Exception for event: %s', event)

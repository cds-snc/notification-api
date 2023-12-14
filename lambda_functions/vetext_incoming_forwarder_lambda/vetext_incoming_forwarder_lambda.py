""" This module is used to transfer incoming twilio requests to a Vetext endpoint. """
import base64
import json
import logging
import os
import sys
from functools import lru_cache
from urllib.parse import parse_qsl, parse_qs

import boto3
import requests
from twilio.request_validator import RequestValidator

logger = logging.getLogger("vetext_incoming_forwarder_lambda")

# http timeout for calling vetext endpoint
HTTPTIMEOUT = (3.05, 1)

TWILIO_AUTH_TOKEN_SSM_NAME = os.getenv("TWILIO_AUTH_TOKEN_SSM_NAME")

if TWILIO_AUTH_TOKEN_SSM_NAME is None or TWILIO_AUTH_TOKEN_SSM_NAME == "DEFAULT":
    sys.exit("A required environment variable is not set. Please set TWILIO_AUTH_TOKEN_SSM_NAME")


def get_twilio_token() -> str:
    """
    Is run on instantiation.
    Defined here and in delivery_status_processor
    @return: Twilio Token from SSM
    """
    try:
        if TWILIO_AUTH_TOKEN_SSM_NAME == 'unit_test':
            return "bad_twilio_auth"
        ssm_client = boto3.client("ssm", "us-gov-west-1")
        auth_ssm_key = os.getenv("TWILIO_AUTH_TOKEN_SSM_NAME", "")
        if not auth_ssm_key:
            logger.error("TWILIO_AUTH_TOKEN_SSM_NAME not set")

        response = ssm_client.get_parameter(
            Name=auth_ssm_key,
            WithDecryption=True
        )
        return response.get("Parameter").get("Value")
    except Exception as e:
        logger.error('Failed to retrieve Twilio Auth')
        return None


auth_token = get_twilio_token()


def validate_twilio_event(event: dict) -> bool:
    """
    Defined both here and in delivery_status_processor.
    Validates that event was from Twilio.
    @param: event
    @return: bool
    """
    logger.info("validating twilio vetext forwarder event")

    try:
        signature = event["headers"].get("x-twilio-signature", "")
        if not auth_token or not signature:
            logger.error("TWILIO_AUTH_TOKEN or signature not set")
            return False

        validator = RequestValidator(auth_token)
        uri = f"https://{event['headers']['host']}/vanotify/twoway/vettext"
        decoded = base64.b64decode(event.get("body")).decode()
        params = parse_qs(decoded)
        params = {k: v[0] for k, v in (params.items())}
        return validator.validate(
            uri=uri,
            params=params,
            signature=signature
        )
    except Exception as e:
        logger.error("Error validating request origin: %s", e)
        return False


def vetext_incoming_forwarder_lambda_handler(event: dict, context: any):
    """this method takes in an event passed in by either an alb or sqs.
        @param: event   -  contains data pertaining to an incoming sms from Twilio
        @param: context -  contains information regarding information
            regarding what triggered the lambda (context.invoked_function_arn).
    """
    try:
        logger.debug("Entrypoint event: %s", event)
        # Determine if the invoker of the lambda is SQS or ALB
        #   SQS will submit batches of records so there is potential for multiple events to be processed
        #   ALB will submit a single request but to simplify code, it will also return an array of event bodies
        if "requestContext" in event and "elb" in event["requestContext"]:
            logger.info("alb invocation")
            if context and not validate_twilio_event(event):
                logger.info("Returning 403 on unauthenticated Twilio request")
                return create_twilio_response(403)
            logger.info("Authenticated Twilio request")
            event_bodies = process_body_from_alb_invocation(event)
        elif "Records" in event:
            logger.info("sqs invocation")
            event_bodies = process_body_from_sqs_invocation(event)
        else:
            logger.error("Invalid Event. Expecting the source of an invocation to be from alb or sqs. Received: %s", event)
            push_to_dead_letter_sqs(event, "vetext_incoming_forwarder_lambda_handler")

            return create_twilio_response(500)

        logger.debug("Successfully processed event to event_bodies. Received: %s", event_bodies)

        for event_body in event_bodies:
            logger.debug("Processing event_body: %s", event_body)

            response = make_vetext_request(event_body)

            if response is None:
                push_to_retry_sqs(event_body)

        return create_twilio_response()
    except Exception as e:
        logger.error("Unexpected exception: %s", e)
        push_to_dead_letter_sqs(event, "vetext_incoming_forwarder_lambda_handler")

        return create_twilio_response(500)


def create_twilio_response(status_code: int = 200):
    response = {
        "headers": {
            "Content-Type": "text/xml"
        },
        "body": "<Response />",
        "statusCode": status_code
    }

    return response


def process_body_from_sqs_invocation(event):
    event_bodies = []
    for record in event["Records"]:
        # record is a sqs event that contains a body
        # body is an alb request that failed in an initial request
        # event is a json document with a body attribute that contains
        #   the payload of the twilio webhook
        # event["body"] is a base 64 encoded string
        # parse_qsl converts url-encoded strings to array of tuple objects
        # event_body takes the array of tuples and creates a dictionary
        try:
            event_body = record.get("body", "")

            if not event_body:
                logger.info("event_body from sqs record was not present")
                logger.debug(record)
                continue

            logger.debug("Processing record body from SQS")
            event_body = json.loads(event_body)
            logger.info("Successfully converted record body from sqs to json")
            event_bodies.append(event_body)
        except json.decoder.JSONDecodeError as je:
            logger.error("Failed to load json event_body: %s", je)
            push_to_dead_letter_sqs(event_body, "process_body_from_sqs_invocation")
        except Exception as e:
            logger.error("Failed to load event from sqs")
            logger.exception(e)
            push_to_dead_letter_sqs(event_body, "process_body_from_sqs_invocation")

    return event_bodies


def process_body_from_alb_invocation(event):
    # event is a json document with a body attribute that contains
    #   the payload of the twilio webhook
    # event["body"] is a base 64 encoded string
    # parse_qsl converts url-encoded strings to array of tuple objects
    # event_body takes the array of tuples and creates a dictionary
    event_body_encoded = event.get("body", "")

    if not event_body_encoded:
        logger.error("event_body from alb record was not present: %s", event)

    event_body_decoded = parse_qsl(base64.b64decode(event_body_encoded).decode("utf-8"))
    logger.debug("Decoded event body %s", event_body_decoded)

    event_body = dict(event_body_decoded)
    logger.debug("Converted body to dictionary: %s", event_body)

    if "AddOns" in event_body:
        logger.debug("AddOns present in event_body: %s", event_body["AddOns"])
        del event_body["AddOns"]

    return [event_body]


@lru_cache(maxsize=None)
def read_from_ssm(key: str) -> str:
    try:
        ssm_client = boto3.client("ssm")

        logger.info("Generated ssm_client")

        response = ssm_client.get_parameter(
            Name=key,
            WithDecryption=True
        )

        logger.info("received ssm parameter")

        return response.get("Parameter", {}).get("Value", "")
    except Exception as e:
        logger.error("General Exception With Call to VeText")
        logger.exception(e)
        return ""


def make_vetext_request(request_body):
    ssm_path = os.getenv("vetext_api_auth_ssm_path")
    if ssm_path is None:
        logger.error("Unable to retrieve vetext_api_auth_ssm_path from env variables")
        return None

    domain = os.getenv("vetext_api_endpoint_domain")
    if domain is None:
        logger.error("Unable to retrieve vetext_api_endpoint_domain from env variables")
        return None

    path = os.getenv("vetext_api_endpoint_path")
    if path is None:
        logger.error("Unable to retrieve vetext_api_endpoint_path from env variables")
        return None

    # Authorization is basic token authentication that is stored in environment.
    auth_token = read_from_ssm(ssm_path)

    if auth_token == "":
        logger.error("Unable to retrieve auth token from SSM")
        return None

    logger.info("Retrieved AuthToken from SSM")

    headers = {
        "Content-type": "application/json",
        "Authorization": "Basic " + auth_token
    }

    body = {
        "accountSid": request_body.get("AccountSid", ""),
        "messageSid": request_body.get("MessageSid", ""),
        "messagingServiceSid": request_body.get("MessagingServiceSid", ""),
        "to": request_body.get("To", ""),
        "from": request_body.get("From", ""),
        "messageStatus": request_body.get("SmsStatus", ""),
        "body": request_body.get("Body", "")
    }

    endpoint_uri = f"https://{domain}{path}"

    logger.info("Making POST Request to VeText using: %s", endpoint_uri)
    logger.debug("json dumps: %s", json.dumps(body))

    try:        
        response = requests.post(
            endpoint_uri,
            verify=False,
            json=body,
            timeout=HTTPTIMEOUT,
            headers=headers
        )
        logger.info("VeText POST complete")
        response.raise_for_status()
        
        logger.info("VeText call complete with response: %d", response.status_code)
        logger.debug("VeText response: %s", response.content)
        return response.content
    except requests.HTTPError as e:
        logger.error("HTTPError With Call To VeText")
        logger.exception(e)
    except requests.RequestException as e:
        logger.error("RequestException With Call To VeText")
        logger.exception(e)
    except Exception as e:
        logger.error("General Exception With Call to VeText")
        logger.exception(e)
    
    return None


def push_to_retry_sqs(event_body):
    """Places event body dictionary on queue to be retried at a later time"""
    logger.info("Placing event_body on retry queue")
    logger.debug("Preparing for Retry SQS: %s", event_body)

    queue_url = os.getenv("vetext_request_drop_sqs_url")

    if queue_url is None:
        logger.error("Unable to retrieve vetext_request_drop_sqs_url from env variables")
        logger.error(event_body)
        return None

    logger.debug("Retrieved queue_url: %s", queue_url)

    try:
        sqs = boto3.client("sqs", "us-west-1")

        queue_msg = json.dumps(event_body)
        queue_msg_attrs = {
            "source": {
                "DataType": "String",
                "StringValue": "twilio"
            }
        }

        sqs.send_message(QueueUrl=queue_url,
                         MessageAttributes=queue_msg_attrs,
                         MessageBody=queue_msg)

        logger.info("Completed enqueue of message to retry queue")
    except Exception as e:
        logger.error("Push to Retry SQS Exception")
        logger.error(event_body)
        logger.exception(e)
        push_to_dead_letter_sqs(event_body, "push_to_retry_sqs")


def push_to_dead_letter_sqs(event, source):
    """Places unaccounted for event on dead-letter queue to be inspected"""

    logger.info("Placing event on dead-letter queue")
    logger.debug("Preparing for DeadLetter SQS: %s", event)

    queue_url = os.getenv("vetext_request_dead_letter_sqs_url")

    if queue_url is None:
        logger.error("Unable to retrieve vetext_request_dead_letter_sqs_url from env variables")
        logger.error(event)
        return None

    logger.debug("Retrieved queue_url: %s", queue_url)

    try:
        sqs = boto3.client("sqs")

        queue_msg = json.dumps(event)
        queue_msg_attrs = {
            "source": {
                "DataType": "String",
                "StringValue": source
            }
        }

        sqs.send_message(QueueUrl=queue_url,
                         MessageAttributes=queue_msg_attrs,
                         MessageBody=queue_msg)

        logger.info("Completed enqueue of message to dead letter queue")
    except Exception as e:
        logger.error("Push to Dead Letter SQS Exception")
        logger.error(event)
        logger.exception(e)

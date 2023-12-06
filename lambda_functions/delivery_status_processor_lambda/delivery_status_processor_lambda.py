"""This module is used to determine the source of an external delivery status and route it to the proper queue"""
import base64
import json
import logging
import os
import sys
import uuid
from typing import Optional

import boto3
from twilio.request_validator import RequestValidator

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
CELERY_TASK = os.getenv("CELERY_TASK_NAME", "process-delivery-status-result")
ROUTING_KEY = os.getenv("ROUTING_KEY", "delivery-status-result-tasks")
DELIVERY_STATUS_RESULT_TASK_QUEUE = os.getenv("DELIVERY_STATUS_RESULT_TASK_QUEUE")
DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER = os.getenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER")


SQS_DELAY_SECONDS = 10

if DELIVERY_STATUS_RESULT_TASK_QUEUE is None:
    sys.exit("A required environment variable is not set. Please set DELIVERY_STATUS_RESULT_TASK_QUEUE")

if DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER is None:
    sys.exit("A required environment variable is not set. Please set DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER")

sqs_client = boto3.client("sqs", region_name="us-gov-west-1")

logger = logging.getLogger("delivery-status-processor-lambda")

try:
    logger.setLevel(LOG_LEVEL)
except ValueError:
    logger.setLevel("INFO")
    logger.warning("Invalid log level specified, defaulting to INFO")


# Duplicated in vetext_incoming_forwarder.
def validate_twilio_event(event):
    uri = f"https://{event['headers']['host']}/twoway/vettext"
    auth_token = os.getenv('TWILIO_AUTH_TOKEN', '')
    # avoid key error
    signature = event['headers'].get('x-twilio-signature', False)
    if not auth_token or not signature:
        logger.error("TWILIO_AUTH_TOKEN not set")
        return False
    validator = RequestValidator(auth_token)
    return validator.validate(
        uri=uri,
        params={'body': event['body']},
        signature=event['headers']['x-twilio-signature']
    )


def delivery_status_processor_lambda_handler(event: any, context: any):
    """this method takes in an event passed in by either an alb.
    @param: event   -  contains data pertaining to an sms delivery status from the external provider
    @param: context -  contains information regarding information
        regarding what triggered the lambda (context.invoked_function_arn).
    """

    try:
        logger.debug("Event: %s", event)

        if not valid_event(event):
            logger.error("Invalid event: %s", event)
            raise Exception("Invalid event")

        logger.info("Valid ALB request received")
        logger.debug(event["body"])

        celery_body = event_to_celery_body_mapping(event)
        if celery_body['provider'] == 'twilio' and not validate_twilio_event(event):
            return {
                "statusCode": 403,
            }

        if celery_body is None:
            logger.error("Unable to generate the celery body for event: %s", event)
            raise Exception("Unable to generate celery body from event")

        logger.info("Successfully generated celery body")
        logger.debug(celery_body)

        celery_task_body = celery_body_to_celery_task(celery_body)

        logger.info("Successfully generated celery task")
        logger.debug(celery_task_body)

        push_to_sqs(celery_task_body, DELIVERY_STATUS_RESULT_TASK_QUEUE, True)

        logger.info("Processing of request complete")

        return {
            "statusCode": 200,
        }

    except Exception as e:
        # Place request on dead letter queue so that it can be analyzed
        #   for potential processing at a later time
        logger.critical("Unknown Failure: %s", e)
        push_to_sqs(event, DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER, False)


def valid_event(event: dict) -> bool:
    """
    Ensure that event data is from the ALB and that it contains
    a user-agent field in the headers
    """

    if event is None:
        logger.error("event is None: %s", event)
    elif "body" not in event or "headers" not in event:
        logger.error("Missing from event object: %s", event)
    elif "user-agent" not in event["headers"]:
        logger.error('Missing "user-agent" from: %s', event.get("headers"))
    else:
        return True

    return False


def event_to_celery_body_mapping(event: dict) -> Optional[dict]:
    """
    Determines which SQS queue to send the message to based on the message type
    """
    if "TwilioProxy" in event["headers"]["user-agent"]:
        return {"body": event["body"], "provider": "twilio"}
    else:
        return None


def celery_body_to_celery_task(task_message: dict) -> dict:
    """
    A celery task is created.
    The envelope has a generic schema that can be consumed by before it routes to a task
    The task is used to route the message to the proper method in the app
    """
    task = {
        "task": CELERY_TASK,
        "id": str(uuid.uuid4()),
        "args": [{"message": task_message}],
        "kwargs": {},
        "retries": 0,
        "eta": None,
        "expires": None,
        "utc": True,
        "callbacks": None,
        "errbacks": None,
        "timelimit": [None, None],
        "taskset": None,
        "chord": None,
    }
    envelope = {
        "body": base64.b64encode(bytes(json.dumps(task), "utf-8")).decode("utf-8"),
        "content-encoding": "utf-8",
        "content-type": "application/json",
        "headers": {},
        "properties": {
            "reply_to": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "delivery_mode": 2,
            "delivery_info": {"priority": 0, "exchange": "default", "routing_key": ROUTING_KEY},
            "body_encoding": "base64",
            "delivery_tag": str(uuid.uuid4()),
        },
    }

    return envelope


def push_to_sqs(push_data: dict, queue_url: str, encode: bool) -> None:
    """
    Pushes an inbound sms or entire event to SQS. Sends to RETRY or DEAD LETTER queue dependent
    on is_retry variable.
    """

    logger.info("Pushing to the %s queue . . .", queue_url)
    logger.debug("SQS push data: %s", push_data)

    if push_data is None:
        logger.critical("Unable to push data to SQS.  The data is being dropped: %s", push_data)
        return

    try:
        if encode:
            queue_msg = base64.b64encode(bytes(json.dumps(push_data), "utf-8")).decode("utf-8")
        else:
            queue_msg = json.dumps(push_data)

    except TypeError as e:
        # Unable enqueue the data in any queue.  Don't try sending it to the dead letter queue.
        logger.exception(e)
        logger.critical(". . . Unable to generate queue_msg. The data is being dropped: %s", push_data)
        return

    except Exception as e:
        # Unable enqueue the data in any queue.  Don't try sending it to the dead letter queue.
        logger.exception(e)
        logger.critical(". . . Unable to generate queue_msg. The data is being dropped: %s", push_data)
        return

    # NOTE: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_SendMessage.html
    # Need to ensure none of those unicode characters are in the message or it's gone.
    try:
        sqs_client.send_message(QueueUrl=queue_url, MessageBody=queue_msg, DelaySeconds=SQS_DELAY_SECONDS)

        logger.info(". . . Completed the SQS push.")

    except Exception as e:
        logger.exception(e)
        logger.critical(". . . Failed to push to SQS with data: %s", push_data)

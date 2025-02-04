import base64
import json
import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError

# constants
AWS_REGION = 'us-gov-west-1'
ROUTING_KEY = 'delivery-status-result-tasks'

# environment variables
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# set up logger
logger = logging.getLogger('PinpointCallbackLambda')

try:
    logger.setLevel(LOG_LEVEL)
except ValueError:
    logger.setLevel('INFO')
    logger.warning('Invalid log level specified. Defaulting to INFO.')

# set up sqs resource
queue_name = f'{os.getenv("NOTIFICATION_QUEUE_PREFIX")}{ROUTING_KEY}'
try:
    sqs = boto3.resource('sqs', region_name=AWS_REGION)
    queue = sqs.get_queue_by_name(QueueName=queue_name)
except ClientError as e:
    logger.critical(
        'ClientError, failed to create SQS resource or could not get sqs queue "%s". Exception: %s', queue_name, e
    )
    raise
except Exception as e:
    logger.critical(
        'Exception, failed to create SQS resource or could not get sqs queue "%s". Exception: %s', queue_name, e
    )
    raise


def lambda_handler(
    event,
    context,
):
    for record in event['Records']:
        task = {
            'task': 'process-pinpoint-result',
            'id': str(uuid.uuid4()),
            'args': [{'Message': record['kinesis']['data']}],
            'kwargs': {},
            'retries': 0,
            'eta': None,
            'expires': None,
            'utc': True,
            'callbacks': None,
            'errbacks': None,
            'timelimit': [None, None],
            'taskset': None,
            'chord': None,
        }
        envelope = {
            'body': base64.b64encode(bytes(json.dumps(task), 'utf-8')).decode('utf-8'),
            'content-encoding': 'utf-8',
            'content-type': 'application/json',
            'headers': {},
            'properties': {
                'reply_to': str(uuid.uuid4()),
                'correlation_id': str(uuid.uuid4()),
                'delivery_mode': 2,
                'delivery_info': {'priority': 0, 'exchange': 'default', 'routing_key': ROUTING_KEY},
                'body_encoding': 'base64',
                'delivery_tag': str(uuid.uuid4()),
            },
        }

        msg = base64.b64encode(bytes(json.dumps(envelope), 'utf-8')).decode('utf-8')
        try:
            queue.send_message(MessageBody=msg)
        except ClientError as e:
            logger.critical('ClientError, failed to send message to SQS queue "%s". Exception: %s', queue_name, e)
            raise
        except Exception as e:
            logger.critical('Exception, failed to send message to SQS queue "%s". Exception: %s', queue_name, e)
            raise

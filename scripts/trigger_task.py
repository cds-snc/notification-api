import base64
import json

import boto3
import uuid
import argparse


def send_task(
    task_name,
    queue_prefix,
    routing_key,
    task_args,
):
    sqs = boto3.resource('sqs', region_name='us-gov-west-1')
    queue = sqs.get_queue_by_name(QueueName=f'{queue_prefix}{routing_key}')

    task = {
        'task': task_name,
        'id': str(uuid.uuid4()),
        'args': task_args,
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
            'delivery_info': {'priority': 0, 'exchange': 'default', 'routing_key': routing_key},
            'body_encoding': 'base64',
            'delivery_tag': str(uuid.uuid4()),
        },
    }

    msg = base64.b64encode(bytes(json.dumps(envelope), 'utf-8')).decode('utf-8')
    queue.send_message(MessageBody=msg)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--task-name', dest='task_name', type=str, default='generate-daily-notification-status-csv-report'
    )
    parser.add_argument('--queue-prefix', dest='queue_prefix', type=str, default='dev-notification-')
    parser.add_argument('--routing-key', dest='routing_key', type=str, default='delivery-status-result-tasks')
    parser.add_argument('--task-args', dest='task_args', nargs='+', default=[])

    args = parser.parse_args()
    send_task(args.task_name, args.queue_prefix, args.routing_key, args.task_args)

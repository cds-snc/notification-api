"""
Script to test the SQS rate limit of 10 messages / second.

Uses boto, so relies on correctly set up AWS access keys and tokens.

Usage:
    test_sqs_queue_rate.py <action>

    options are:
    - setup: Create a queue and put messages to fetch.
    - test: Test the queue by fetching the queue in batches.
    - cleanup: Delete the test queue and its messages.

Example:
        test_sqs_queue_rate.py
"""

import boto3
from botocore.exceptions import ClientError
from docopt import docopt

AWS_REGION = "ca-central-1"
QUEUE_NAME = "test-rate-sqs.fifo"
SQS_MAX_SEND = 10
TEST_TOTAL_MSG = 100

sqs = boto3.resource("sqs", region_name=AWS_REGION)


def cleanup_batch_queue(queue_name: str):
    q = _get_queue(queue_name)
    if q:
        q.delete()
        print(f"Deleted queue {queue_name}")


def setup_queue(queue_name: str):
    q = _create_or_get_queue(queue_name)
    if not q:
        return None
    entries = _get_entries(group_id=0, num=TEST_TOTAL_MSG)
    response = _create_messages(q, entries)
    return response


def test_batch_queue(queue):
    try:
        for message in queue.receive_messages(MessageAttributeNames=['All']):
            name = message.message_attributes.get('Author').get('StringValue')
            print(f"Retrieved message for {name}; deleting...")
            message.delete()
    except sqs.meta.client.exceptions.LimitExceededException:
        print('API call limit exceeded; backing off and retrying...')


def _chunk(arr: list, size: int) -> list[list]:
    return [arr[i : i + size] for i in range(len(arr))[::size]]


def _create_msg(group_id: int = 0, counter: int = -1):
    while True:
        counter += 1
        yield {
            "Id": f"{counter}",
            "MessageBody": f"boto{counter + 42}",
            "MessageAttributes": {"Author": {"StringValue": "Anonymous", "DataType": "String"}},
            "MessageGroupId": str(group_id),
        }


def _create_messages(queue, messages: list) -> list:
    responses = []
    for batch in _chunk(messages, SQS_MAX_SEND):
        response = queue.send_messages(Entries=batch)
        responses.append(response)
    return responses


def _create_or_get_queue(queue_name: str):
    try:
        queue = sqs.get_queue_by_name(QueueName=queue_name)
        return queue
    except sqs.meta.client.exceptions.QueueDoesNotExist:
        return _create_queue(queue_name)
    else:
        print(f"Could not get or create queue {queue_name}!")
        return None


def _create_queue(queue_name: str):
    try:
        queue = sqs.create_queue(
            QueueName=queue_name, Attributes={"ContentBasedDeduplication": "true", "DelaySeconds": "1", "FifoQueue": "true"}
        )
        return queue
    except ClientError as error:
        print(f"Could not create queue {queue_name}!")
        print(error.response)
        return None


def _get_entries(group_id: int = 0, num: int = 5) -> list[dict]:
    itr = _create_msg(group_id)
    entries = [next(itr) for _ in range(num)]
    return entries


def _get_queue(queue_name: str):
    try:
        queue = sqs.get_queue_by_name(QueueName=queue_name)
        return queue
    except sqs.meta.client.exceptions.QueueDoesNotExist:
        print(f"The queue {queue_name} does not exist!")
    except ClientError as error:
        print(f"Could not retrieve queue {queue_name}!")
        print(error.response)
    else:
        print(f"Could not get or create queue {queue_name}!")
        return None


if __name__ == "__main__":
    arguments = docopt(__doc__)

    if arguments["<action>"] == "setup":
        response = setup_queue(QUEUE_NAME)
        if response is None:
            print(f"Could not setup queue {QUEUE_NAME}\n\n")
        else:
            print(f"response={response}\n\n")
        print(f"Done executing setup queue {QUEUE_NAME}")
    elif arguments["<action>"] == "test":
        test_batch_queue(QUEUE_NAME)
        print(f"Done testing batch queue {QUEUE_NAME}")
    elif arguments["<action>"] == "cleanup":
        cleanup_batch_queue(QUEUE_NAME)
        print(f"Cleaned up batch queue {QUEUE_NAME}")
    else:
        print("UNKNOWN COMMAND")
        exit(1)

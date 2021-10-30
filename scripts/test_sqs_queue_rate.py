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
        test_sqs_queue_rate.py test
"""

import boto3
from botocore.exceptions import ClientError
from docopt import docopt
import uuid


AWS_REGION = "ca-central-1"
QUEUE_NAME = "test-rate-sqs.fifo"
SQS_MAX_RECEIVE = 10
SQS_MAX_SEND = 10
TEST_TOTAL_MSG = 20000

sqs = boto3.resource("sqs", region_name=AWS_REGION)
sqs_client = boto3.client("sqs", region_name=AWS_REGION)


class TestSqsException(BaseException):
    def __init__(self, message):
        self.message = message


def cleanup_batch_queue(queue_name: str):
    q = _sqs_get_queue(queue_name)
    if q:
        q.delete()
        print(f"Deleted queue {queue_name}")


def setup_queue(queue_name: str):
    q = _sqs_create_or_get_queue(queue_name)
    entries = _get_entries(group_id=str(uuid.uuid4()), num=TEST_TOTAL_MSG)
    messages = _sqs_send_messages(q, entries)
    return (q, messages)


def test_batch_queue(queue_name):
    q = _sqs_get_queue(queue_name)
    if not q:
        print(f"No queue {queue_name} exists, need to set it up!")
    messages = _sqs_get_messages(q, SQS_MAX_RECEIVE)
    while len(messages) > 0:
        deletions = []
        for message in messages:
            deletions.append({
                'Id': message.message_id,
                'ReceiptHandle': message.receipt_handle
            })
            print(f"Retrieved message for {message.body}; deleting...")
        sqs_client.delete_message_batch(QueueUrl=q.url, Entries=deletions)
        messages = _sqs_get_messages(q, SQS_MAX_RECEIVE)


def _chunk(arr: list, size: int) -> list[list]:
    return [arr[i : i + size] for i in range(len(arr))[::size]]


def _create_msg(group_id: str, counter: int = -1):
    while True:
        counter += 1
        yield {
            "Id": f"{counter}",
            "MessageBody": f"boto{counter + 42}",
            "MessageAttributes": {"Author": {"StringValue": "Anonymous", "DataType": "String"}},
            "MessageGroupId": group_id,
        }


def _get_entries(group_id: str, num: int = 5) -> list[dict]:
    itr = _create_msg(group_id)
    entries = [next(itr) for _ in range(num)]
    return entries


def _sqs_create_queue(queue_name: str):
    try:
        queue = sqs.create_queue(
            QueueName=queue_name, Attributes={"ContentBasedDeduplication": "true", "DelaySeconds": "1", "FifoQueue": "true"}
        )
        return queue
    except ClientError as error:
        raise TestSqsException(f"Could not create queue {queue_name}!\n{error.response}")


def _sqs_create_or_get_queue(queue_name: str):
    try:
        queue = sqs.get_queue_by_name(QueueName=queue_name)
        return queue
    except sqs.meta.client.exceptions.QueueDoesNotExist:
        return _sqs_create_queue(queue_name)
    else:
        raise TestSqsException(f"Could not get or create queue {queue_name}!")


def _sqs_get_messages(queue, max_receive: int = SQS_MAX_RECEIVE):
    try:
        return queue.receive_messages(MessageAttributeNames=["All"], MaxNumberOfMessages=max_receive)
    except ClientError as error:
        raise TestSqsException(f"Could not get messages from queue!\n{error.response}")


def _sqs_get_queue(queue_name: str):
    try:
        queue = sqs.get_queue_by_name(QueueName=queue_name)
        return queue
    except sqs.meta.client.exceptions.QueueDoesNotExist:
        print(f"The queue {queue_name} does not exist!")
        return None
    except ClientError as error:
        raise TestSqsException(f"Could not retrieve queue {queue_name}!\n{error.response}")
    else:
        raise TestSqsException(f"Could not get or create queue {queue_name}!")


def _sqs_send_messages(queue, messages: list) -> list:
    message_ids: list[str] = []
    for batch in _chunk(messages, SQS_MAX_SEND):
        response = queue.send_messages(Entries=batch)
        ids = [r['MessageId'] for r in response['Successful']]
        print(f"Created messages: {ids}")
        message_ids.extend(ids)
    return message_ids


if __name__ == "__main__":
    arguments = docopt(__doc__)

    if arguments["<action>"] == "setup":
        (queue, response) = setup_queue(QUEUE_NAME)
        if queue is None:
            print(f"Could not setup queue {QUEUE_NAME}\n\n")
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

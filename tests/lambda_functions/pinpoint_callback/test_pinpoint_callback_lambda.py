import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws


def test_pinpoint_callback_lambda_raises_client_error():
    # Without the SQS data being available to the lambda, expect a ClientError.
    with pytest.raises(ClientError):
        import lambda_functions.pinpoint_callback.pinpoint_callback_lambda


@mock_aws
def test_pinpoint_callback_lambda_handler_success():
    sqs = boto3.resource('sqs', region_name='us-gov-west-1')
    sqs.create_queue(QueueName='vanotify-delivery-status-result-tasks')
    sqs.create_queue(QueueName='test-notification-delivery-status-result-tasks')

    # The import attempts to initialize the SQS resources, has to be imported after the fixture has ran
    from lambda_functions.pinpoint_callback.pinpoint_callback_lambda import lambda_handler

    # test data
    event = {'Records': [{'kinesis': {'data': 'test-data'}}]}
    context = {}

    lambda_handler(event, context)

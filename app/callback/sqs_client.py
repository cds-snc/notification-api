import json

import boto3
from botocore.exceptions import ClientError


class SQSClient:
    def __init__(self):
        self.name = 'sqs'

    def init_app(
        self,
        aws_region,
        logger,
        statsd_client,
    ):
        self._client = boto3.client('sqs', region_name=aws_region)
        self.aws_region = aws_region
        self.statsd_client = statsd_client
        self.logger = logger

    def get_name(self):
        return self.name

    def send_message(
        self,
        url: str,
        message_body: dict,
        message_attributes: dict = None,
    ):
        if not message_attributes:
            message_attributes = {}
        message_attributes['ContentType'] = {'StringValue': 'application/json', 'DataType': 'String'}
        try:
            # if SQS is fifo then
            if 'fifo' in url:
                response = self._client.send_message(
                    QueueUrl=url,
                    MessageBody=json.dumps(message_body),
                    MessageAttributes=message_attributes,
                    MessageGroupId=url,
                )
            else:
                response = self._client.send_message(
                    QueueUrl=url,
                    MessageBody=json.dumps(message_body),
                    MessageAttributes=message_attributes,
                )
        except ClientError:
            self.logger.exception('SQS client failed to send message: %s', message_body)
            raise
        else:
            return response

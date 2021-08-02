import boto3
from botocore.exceptions import ClientError

from app.celery.exceptions import NonRetryableException


class SQSClient:
    def __init__(self):
        self.name = 'sqs'

    def init_app(self, aws_region, logger, statsd_client):
        self._client = boto3.client('sqs', region_name=aws_region)
        self.aws_region = aws_region
        self.statsd_client = statsd_client
        self.logger = logger

    def get_name(self):
        return self.name

    def send_message(self, url: str, message_body: dict, message_attributes: dict = None):
        try:
            response = self._client.send_message(
                QueueUrl=url, MessageBody=message_body, MessageAttributes=message_attributes
            )
        except ClientError as e:
            self.logger.error("Send message failed: %s", message_body)
            raise NonRetryableException(e)
        else:
            return response

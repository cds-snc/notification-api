import boto3


class SQSClient:
    def __init__(self):
        self.name = 'sqs'

    def init_app(self, sqs_url, aws_region, logger, statsd_client):
        self._client = boto3.client('sqs', region_name=aws_region)
        self.sqs_url = sqs_url
        self.aws_region = aws_region
        self.statsd_client = statsd_client
        self.logger = logger

    def get_name(self):
        return self.name

    def send_message(self, message_body):
        self._client.send_message(QueueUrl=self.sqs_url, MessageBody=message_body)

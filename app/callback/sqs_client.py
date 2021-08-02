import boto3


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

    def send_message(self, url, message_body):
        self._client.send_message(URL=url, MessageBody=message_body)

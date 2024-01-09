import boto3
import botocore
from time import monotonic
from app.clients.sms import SmsClient, SmsClientResponseException


class SnsClientException(SmsClientResponseException):
    pass


class AwsSnsClient(SmsClient):
    """
    AwsSns sms client
    """

    def __init__(self) -> None:
        self.name = 'sns'

    def init_app(
        self,
        aws_region,
        statsd_client,
        logger,
        *args,
        **kwargs,
    ):
        self._client = boto3.client('sns', region_name=aws_region)
        super().__init__(*args, **kwargs)
        self.logger = logger
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_sms(
        self,
        to,
        content,
        reference,
        multi=True,
        sender=None,
        **kwargs,
    ):
        try:
            start_time = monotonic()
            response = self._client.publish(
                PhoneNumber=to,
                Message=content,
                MessageAttributes={'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'}},
            )
        except (botocore.exceptions.ClientError, Exception) as e:
            self.statsd_client.incr('clients.sns.error')
            raise SnsClientException(str(e))
        else:
            elapsed_time = monotonic() - start_time
            self.logger.info(f'AWS SNS request finished in {elapsed_time}')
            self.statsd_client.timing('clients.sns.request-time', elapsed_time)
            self.statsd_client.incr('clients.sns.success')
            return response['MessageId']

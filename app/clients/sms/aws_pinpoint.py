import boto3
import botocore
from time import monotonic
from app.clients.sms import SmsClient, SmsClientResponseException


class AwsPinpointException(SmsClientResponseException):
    pass


class AwsPinpointClient(SmsClient):
    """
    AwsSns pinpoint client
    """
    def __init__(self):
        self.name = 'pinpoint'

    def init_app(self, aws_pinpoint_app_id, aws_region, logger, origination_number, statsd_client):
        self._client = boto3.client('pinpoint', region_name=aws_region)
        self.aws_pinpoint_app_id = aws_pinpoint_app_id
        self.aws_region = aws_region
        self.origination_number = origination_number
        self.statsd_client = statsd_client
        self.logger = logger

    def get_name(self):
        return self.name

    def send_sms(self, to: str, content, reference, multi=True, sender=None):
        sender_id = self.origination_number if sender is None else sender
        recipient_number = str(to)

        try:
            start_time = monotonic()
            response = self._post_message_request(recipient_number, content, sender_id)

        except (botocore.exceptions.ClientError, Exception) as e:
            self.statsd_client.incr("clients.pinpoint.error")
            raise AwsPinpointException(str(e))
        else:
            elapsed_time = monotonic() - start_time
            self.logger.info(f"AWS Pinpoint SMS request finished in {elapsed_time} for {reference}")
            self.statsd_client.timing("clients.pinpoint.request-time", elapsed_time)
            self.statsd_client.incr("clients.pinpoint.success")
            return response['MessageResponse']['Result'][recipient_number]['MessageId']

    def _post_message_request(self, recipient_number, content, sender):
        message_request_payload = {
            "Addresses": {
                recipient_number: {
                    "ChannelType": "SMS"
                }
            },
            "MessageConfiguration": {
                "SMSMessage": {
                    "Body": content,
                    "MessageType": "TRANSACTIONAL",
                    "OriginationNumber": sender
                }
            }
        }

        return self._client.send_messages(
            ApplicationId=self.aws_pinpoint_app_id,
            MessageRequest=message_request_payload
        )

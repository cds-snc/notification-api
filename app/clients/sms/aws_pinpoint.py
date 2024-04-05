import boto3
from botocore.exceptions import ClientError
import phonenumbers
from time import monotonic
from app.clients.sms import SmsClient


class AwsPinpointClient(SmsClient):
    '''
    AWS Pinpoint SMS client
    '''

    def init_app(self, current_app, statsd_client, *args, **kwargs):
        self._client = boto3.client('pinpoint-sms-voice-v2', region_name="ca-central-1")
        super(SmsClient, self).__init__(*args, **kwargs)
        self.current_app = current_app
        self.name = 'pinpoint'
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_sms(self, to, content, reference, multi=True, sender=None):
        pool_id = self.current_app.config['AWS_PINPOINT_POOL_ID']
        messageType = "TRANSACTIONAL"
        matched = False

        for match in phonenumbers.PhoneNumberMatcher(to, "US"):
            matched = True
            to = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            destinationNumber = to
                    
            try:
                start_time = monotonic()
                
                # from https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/pinpoint-sms-voice-v2/client/send_text_message.html
                response = self._client.send_text_message(
                    DestinationPhoneNumber=destinationNumber,
                    OriginationIdentity=pool_id,
                    MessageBody=content,
                    MessageType=messageType,
                )

                # this will be true if the OriginationIdentity does not exist in pinpoint
                if response['MessageResponse']['Result'][destinationNumber]['StatusCode'] == 400:
                    self.statsd_client.incr("clients.pinpoint.error")
                    raise Exception(response['MessageResponse']['Result'][destinationNumber]['StatusMessage'])
            except ClientError as e:
                self.statsd_client.incr("clients.pinpoint.error")
                raise Exception(e)
            except Exception as e:
                self.statsd_client.incr("clients.pinpoint.error")
                raise Exception(e)
            finally:
                elapsed_time = monotonic() - start_time
                self.current_app.logger.info("AWS Pinpoint request finished in {}".format(elapsed_time))
                self.statsd_client.timing("clients.pinpoint.request-time", elapsed_time)
                self.statsd_client.incr("clients.pinpoint.success")

            return response['MessageResponse']['Result'][destinationNumber]['MessageId']

        if not matched:
            self.statsd_client.incr("clients.pinpoint.error")
            self.current_app.logger.error("No valid numbers found in {}".format(to))
            raise ValueError("No valid numbers found for SMS delivery")
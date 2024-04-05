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


        # The phone number or short code to send the message from. The phone number
        # or short code that you specify has to be associated with your Amazon Pinpoint
        # account. For best results, specify long codes in E.164 format.
        # originationNumber = sender

        # The recipient's phone number.  For best results, you should specify the
        # phone number in E.164 format.
        # destinationNumber = "+14255550142"

        # The Amazon Pinpoint project/application ID to use when you send this message.
        # Make sure that the SMS channel is enabled for the project or application
        # that you choose.
        applicationId = self.current_app.config['AWS_PINPOINT_APP_ID']

        # The type of SMS message that you want to send. If you plan to send
        # time-sensitive content, specify TRANSACTIONAL. If you plan to send
        # marketing-related content, specify PROMOTIONAL.
        messageType = "TRANSACTIONAL"

        # The registered keyword associated with the originating short code.
        registeredKeyword = self.current_app.config['AWS_PINPOINT_KEYWORD']
        # The sender ID to use when sending the message. Support for sender ID
        # varies by country or region. For more information, see
        # https://docs.aws.amazon.com/pinpoint/latest/userguide/channels-sms-countries.html
        # senderId = "MySenderID"

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
                    OriginationIdentity=self.pool_id,
                    MessageBody=content,
                    MessageType=messageType,
                    Keyword=registeredKeyword                    
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
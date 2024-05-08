from time import monotonic

import boto3
import phonenumbers

from app.clients.sms import SmsClient

from app.config import Config

class AwsPinpointClient(SmsClient):
    """
    AWS Pinpoint SMS client
    """

    def init_app(self, current_app, statsd_client, *args, **kwargs):
        self._client = boto3.client("pinpoint-sms-voice-v2", region_name="ca-central-1")
        super(AwsPinpointClient, self).__init__(*args, **kwargs)
        # super(SmsClient, self).__init__(*args, **kwargs)
        self.current_app = current_app
        self.name = "pinpoint"
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_sms(self, to, content, reference, multi=True, sender=None, template_id=None):
        messageType = "TRANSACTIONAL"
        matched = False

        if template_id is not None and str(template_id) in Config.AWS_PINPOINT_SC_TEMPLATE_IDS:
            pool_id = Config.AWS_PINPOINT_SC_POOL_ID
        else:
            pool_id = Config.AWS_PINPOINT_DEFAULT_POOL_ID
       
        for match in phonenumbers.PhoneNumberMatcher(to, "US"):
            matched = True
            to = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            destinationNumber = to

            try:
                start_time = monotonic()
                response = self._client.send_text_message(
                    DestinationPhoneNumber=destinationNumber,
                    OriginationIdentity=pool_id,
                    MessageBody=content,
                    MessageType=messageType,
                    ConfigurationSetName=self.current_app.config["AWS_PINPOINT_CONFIGURATION_SET_NAME"],
                )
            except Exception as e:
                self.statsd_client.incr("clients.pinpoint.error")
                raise Exception(e)
            finally:
                elapsed_time = monotonic() - start_time
                self.current_app.logger.info("AWS Pinpoint request finished in {}".format(elapsed_time))
                self.statsd_client.timing("clients.pinpoint.request-time", elapsed_time)
                self.statsd_client.incr("clients.pinpoint.success")
            return response["MessageId"]

        if not matched:
            self.statsd_client.incr("clients.pinpoint.error")
            self.current_app.logger.error("No valid numbers found in {}".format(to))
            raise ValueError("No valid numbers found for SMS delivery")

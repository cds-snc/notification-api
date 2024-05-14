import re
from time import monotonic

import boto3
import botocore
import phonenumbers
from notifications_utils.statsd_decorators import statsd

from app.clients.sms import SmsClient


class AwsSnsClient(SmsClient):
    """
    AwsSns sms client
    """

    def init_app(self, current_app, statsd_client, *args, **kwargs):
        self._client = boto3.client("sns", region_name=current_app.config["AWS_REGION"])
        self._long_codes_client = boto3.client("sns", region_name=current_app.config["AWS_PINPOINT_REGION"])
        super(SmsClient, self).__init__(*args, **kwargs)
        self.current_app = current_app
        self.name = "sns"
        self.statsd_client = statsd_client
        self.long_code_regex = re.compile(r"^\+1\d{10}$")

    def get_name(self):
        return self.name

    @statsd(namespace="clients.sns")
    def send_sms(self, to, content, reference, multi=True, sender=None, template_id=None):
        matched = False

        for match in phonenumbers.PhoneNumberMatcher(to, "US"):
            matched = True
            to = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)

            client = self._client
            # See documentation
            # https://docs.aws.amazon.com/sns/latest/dg/sms_publish-to-phone.html#sms_publish_sdk
            attributes = {
                "AWS.SNS.SMS.SMSType": {
                    "DataType": "String",
                    "StringValue": "Transactional",
                }
            }

            # If sending with a long code number, we need to use another AWS region
            # and specify the phone number we want to use as the origination number
            send_with_dedicated_phone_number = self._send_with_dedicated_phone_number(sender)
            if send_with_dedicated_phone_number:
                client = self._long_codes_client
                attributes["AWS.MM.SMS.OriginationNumber"] = {
                    "DataType": "String",
                    "StringValue": sender,
                }

            # If the number is US based, we must use a US Toll Free number to send the message
            country = phonenumbers.region_code_for_number(match.number)
            if country == "US":
                client = self._long_codes_client
                attributes["AWS.MM.SMS.OriginationNumber"] = {
                    "DataType": "String",
                    "StringValue": self.current_app.config["AWS_US_TOLL_FREE_NUMBER"],
                }

            try:
                start_time = monotonic()
                response = client.publish(PhoneNumber=to, Message=content, MessageAttributes=attributes)
            except botocore.exceptions.ClientError as e:
                self.statsd_client.incr("clients.sns.error")
                raise str(e)
            except Exception as e:
                self.statsd_client.incr("clients.sns.error")
                raise str(e)
            finally:
                elapsed_time = monotonic() - start_time
                self.current_app.logger.info("AWS SNS request finished in {}".format(elapsed_time))
                self.statsd_client.timing("clients.sns.request-time", elapsed_time)
                self.statsd_client.incr("clients.sns.success")
            return response["MessageId"]

        if not matched:
            self.statsd_client.incr("clients.sns.error")
            self.current_app.logger.error("No valid numbers found in {}".format(to))
            raise ValueError("No valid numbers found for SMS delivery")

    def _send_with_dedicated_phone_number(self, sender):
        return sender and re.match(self.long_code_regex, sender)

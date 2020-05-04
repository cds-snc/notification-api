import boto3
import botocore
import phonenumbers
from time import monotonic
from app.clients.sms import SmsClient


class AwsSnsClient(SmsClient):
    '''
    AwsSns sms client
    '''

    def init_app(self, current_app, statsd_client, *args, **kwargs):
        self._client = boto3.client('sns', region_name="us-east-1")
        super(SmsClient, self).__init__(*args, **kwargs)
        self.current_app = current_app
        self.name = 'sns'
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_sms(self, to, content, reference, multi=True, sender=None):
        matched = False

        for match in phonenumbers.PhoneNumberMatcher(to, "US"):
            matched = True
            to = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)

            try:
                start_time = monotonic()
                response = self._client.publish(
                    PhoneNumber=to,
                    Message=content,
                    MessageAttributes={
                        'AWS.SNS.SMS.SMSType': {
                            'DataType': 'String',
                            'StringValue': 'Transactional'
                        }
                    }
                )
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
            return response['MessageId']

        if not matched:
            self.statsd_client.incr("clients.sns.error")
            self.current_app.logger.error("No valid numbers found in {}".format(to))
            raise ValueError("No valid numbers found for SMS delivery")

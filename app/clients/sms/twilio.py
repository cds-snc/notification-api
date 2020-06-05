from monotonic import monotonic
from app.clients.sms import SmsClient
from twilio.rest import Client

from app.models import NOTIFICATION_TECHNICAL_FAILURE, NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_DELIVERED, \
    NOTIFICATION_SENT, NOTIFICATION_SENDING, NOTIFICATION_CREATED

twilio_response_map = {
    'accepted': NOTIFICATION_CREATED,
    'queued': NOTIFICATION_SENDING,
    'sending': NOTIFICATION_SENDING,
    'sent': NOTIFICATION_SENT,
    'delivered': NOTIFICATION_DELIVERED,
    'undelivered': NOTIFICATION_PERMANENT_FAILURE,
    'failed': NOTIFICATION_TECHNICAL_FAILURE,
    'received': 'received'
}


def get_twilio_responses(status):
    return twilio_response_map[status]


class TwilioSMSClient(SmsClient):
    def __init__(self,
                 account_sid=None,
                 auth_token=None,
                 from_number=None,
                 *args, **kwargs):
        super(TwilioSMSClient, self).__init__(*args, **kwargs)
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._client = Client(account_sid, auth_token)

    def init_app(self, logger, callback_notify_url_host, *args, **kwargs):
        self.logger = logger
        self._callback_notify_url_host = callback_notify_url_host

    @property
    def name(self):
        return 'twilio'

    def get_name(self):
        return self.name

    def send_sms(self, to, content, reference, sender=None):
        # could potentially select from potential numbers like this
        # from_number = random.choice(self._client.incoming_phone_numbers.list()).phone_number

        start_time = monotonic()
        from_number = self._from_number
        callback_url = "{}/notifications/sms/twilio/{}".format(
            self._callback_notify_url_host, reference) if self._callback_notify_url_host else ""
        try:
            message = self._client.messages.create(
                to=to,
                from_=from_number,
                body=content,
                status_callback=callback_url,
            )

            self.logger.info("Twilio send SMS request for {} succeeded: {}".format(reference, message.sid))
        except Exception as e:
            self.logger.error("Twilio send SMS request for {} failed".format(reference))
            raise e
        finally:
            elapsed_time = monotonic() - start_time
            self.logger.info("Twilio send SMS request for {} finished in {}".format(reference, elapsed_time))

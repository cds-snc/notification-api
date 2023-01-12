from monotonic import monotonic
from app.clients.sms import SmsClient
from twilio.rest import Client

twilio_response_map = {
    'accepted': 'created',
    'queued': 'sending',
    'sending': 'sending',
    'sent': 'sent',
    'delivered': 'delivered',
    'undelivered': 'permanent-failure',
    'failed': 'technical-failure',
    'received': 'received'
}


def get_twilio_responses(status):
    return twilio_response_map[status]


class TwilioSMSClient(SmsClient):
    def __init__(self,
                 account_sid=None,
                 auth_token=None,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._client = Client(account_sid, auth_token)

    def init_app(self, logger, callback_notify_url_host, *args, **kwargs):
        self.logger = logger
        self._callback_notify_url_host = callback_notify_url_host

    @property
    def name(self):
        return 'twilio'

    def get_name(self):
        return self.name

    def send_sms(self, to, content, reference, **kwargs) -> str:
        """
        Twilio supports sending messages with a sender phone number or messaging_service_sid.

        Return: a string containing the Twilio message.sid
        """

        start_time = monotonic()
        # TODO: Following two lines are commented out
        # TODO (cont): because the callback url points to an internal url.
        # TODO (cont): When Reverse Proxy ticket(#716)
        # TODO (cont): is complete, we can assign that to callback_url and uncomment
        callback_url = ""
        # if self._callback_notify_url_host:
        #    callback_url = f"{self._callback_notify_url_host}/notifications/sms/twilio/{reference}"

        try:
            # Importing inline to resolve a circular import error when importing at the top of the file
            from app.dao.service_sms_sender_dao import (
                dao_get_service_sms_sender_by_service_id_and_number,
                dao_get_service_sms_sender_by_id
            )
            from_number = None
            messaging_service_sid = None
            sms_sender_id = kwargs.get("sms_sender_id")

            # If sms_sender_id is available, get the specified sender.
            # Otherwise, get the first sender for the service.
            if sms_sender_id is not None:
                # This is an instance of ServiceSmsSender or None.
                service_sms_sender = dao_get_service_sms_sender_by_id(
                    service_id=kwargs.get("service_id"),
                    service_sms_sender_id=sms_sender_id
                )
            else:
                # This is an instance of ServiceSmsSender or None.
                service_sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
                    service_id=kwargs.get("service_id"),
                    number=kwargs.get("sender")
                )

            if service_sms_sender is not None:
                from_number = service_sms_sender.sms_sender

                if service_sms_sender.sms_sender_specifics is not None:
                    messaging_service_sid = service_sms_sender.sms_sender_specifics.get("messaging_service_sid")

                    self.logger.info("Twilio sender has sms_sender_specifics")

            if messaging_service_sid is None:
                # Make a request using a sender phone number.
                message = self._client.messages.create(
                    to=to,
                    from_=from_number,
                    body=content,
                    status_callback=callback_url,
                )

                self.logger.info(f"Twilio message created using from_number")
            else:
                # Make a request using the messaging service sid.
                #    https://www.twilio.com/docs/messaging/services
                message = self._client.messages.create(
                    to=to,
                    messaging_service_sid=messaging_service_sid,
                    body=content,
                    status_callback=callback_url,
                )

                self.logger.info(f"Twilio message created using messaging_service_sid")

            self.logger.info(f"Twilio send SMS request for {reference} succeeded: {message.sid}")

            return message.sid
        except Exception as e:
            self.logger.error(f"Twilio send SMS request for {reference} failed")
            raise e
        finally:
            elapsed_time = monotonic() - start_time
            self.logger.info(f"Twilio send SMS request for {reference} finished in {elapsed_time}")

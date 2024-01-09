import base64
from app.clients.sms import SmsClient
from monotonic import monotonic
from twilio.rest import Client
from urllib.parse import parse_qs


TWILIO_RESPONSE_MAP = {
    'accepted': 'created',
    'queued': 'sending',
    'sending': 'sending',
    'sent': 'sent',
    'delivered': 'delivered',
    'undelivered': 'permanent-failure',
    'failed': 'technical-failure',
    'received': 'received',
}


def get_twilio_responses(status):
    return TWILIO_RESPONSE_MAP[status]


class TwilioSMSClient(SmsClient):
    def __init__(
        self,
        account_sid=None,
        auth_token=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # Twilio docs at.
        # https://www.twilio.com/docs/usage/webhooks/webhooks-connection-overrides
        self.callback_url = None
        self._callback_connection_timeout = 3000  # milliseconds, 10 seconds
        self._callback_read_timeout = 1500  # milliseconds, 15 seconds
        self._callback_retry_count = 5
        self._callback_retry_policy = 'all'
        self._callback_notify_url_host = None
        self.logger = None
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._client = Client(account_sid, auth_token)

        # Importing inline to resolve a circular import error when importing
        # at the top of the file
        from app.models import (
            NOTIFICATION_DELIVERED,
            NOTIFICATION_TECHNICAL_FAILURE,
            NOTIFICATION_SENDING,
            NOTIFICATION_PERMANENT_FAILURE,
            NOTIFICATION_SENT,
        )

        self.twilio_error_code_map = {
            '30001': NOTIFICATION_TECHNICAL_FAILURE,
            '30002': NOTIFICATION_PERMANENT_FAILURE,
            '30003': NOTIFICATION_PERMANENT_FAILURE,
            '30004': NOTIFICATION_PERMANENT_FAILURE,
            '30005': NOTIFICATION_PERMANENT_FAILURE,
            '30006': NOTIFICATION_PERMANENT_FAILURE,
            '30007': NOTIFICATION_PERMANENT_FAILURE,
            '30008': NOTIFICATION_TECHNICAL_FAILURE,
            '30009': NOTIFICATION_TECHNICAL_FAILURE,
            '30010': NOTIFICATION_TECHNICAL_FAILURE,
            '30034': NOTIFICATION_PERMANENT_FAILURE,
        }

        self.twilio_notify_status_map = {
            'accepted': NOTIFICATION_SENDING,
            'scheduled': NOTIFICATION_SENDING,
            'queued': NOTIFICATION_SENDING,
            'sending': NOTIFICATION_SENDING,
            'sent': NOTIFICATION_SENT,
            'delivered': NOTIFICATION_DELIVERED,
            'undelivered': NOTIFICATION_PERMANENT_FAILURE,
            'failed': NOTIFICATION_TECHNICAL_FAILURE,
            'canceled': NOTIFICATION_TECHNICAL_FAILURE,
        }

    def init_app(
        self,
        logger,
        callback_notify_url_host,
        environment,
        *args,
        **kwargs,
    ):
        self.logger = logger
        self._callback_notify_url_host = callback_notify_url_host

        prefix = 'dev-'
        if environment == 'staging':
            prefix = 'staging-'
        elif environment == 'performance':
            prefix = 'sandbox-'
        elif environment == 'production':
            prefix = ''

        self.callback_url = (
            f'https://{prefix}api.va.gov/vanotify/sms/deliverystatus'
            f'#ct={self._callback_connection_timeout}'
            f'&rc={self._callback_retry_count}'
            f'&rt={self._callback_read_timeout}'
            f'&rp={self._callback_retry_policy}'
        )

    @property
    def name(self):
        return 'twilio'

    def get_name(self):
        return self.name

    def send_sms(
        self,
        to,
        content,
        reference,
        **kwargs,
    ) -> str:
        """
        Twilio supports sending messages with a sender phone number
        or messaging_service_sid.

        Return: a string containing the Twilio message.sid
        """

        start_time = monotonic()

        try:
            # Importing inline to resolve a circular import error when
            # importing at the top of the file
            from app.dao.service_sms_sender_dao import (
                dao_get_service_sms_sender_by_service_id_and_number,
                dao_get_service_sms_sender_by_id,
            )

            from_number = None
            messaging_service_sid = None
            sms_sender_id = kwargs.get('sms_sender_id')

            # If sms_sender_id is available, get the specified sender.
            # Otherwise, get the first sender for the service.
            if sms_sender_id is not None:
                # This is an instance of ServiceSmsSender or None.
                service_sms_sender = dao_get_service_sms_sender_by_id(
                    service_id=kwargs.get('service_id'),
                    service_sms_sender_id=sms_sender_id,
                )
            else:
                # This is an instance of ServiceSmsSender or None.
                service_sms_sender = dao_get_service_sms_sender_by_service_id_and_number(
                    service_id=kwargs.get('service_id'), number=kwargs.get('sender')
                )

            if service_sms_sender is not None:
                from_number = service_sms_sender.sms_sender

                if service_sms_sender.sms_sender_specifics is not None:
                    messaging_service_sid = service_sms_sender.sms_sender_specifics.get('messaging_service_sid')

                    self.logger.info('Twilio sender has sms_sender_specifics')

            if messaging_service_sid is None:
                # Make a request using a sender phone number.
                message = self._client.messages.create(
                    to=to,
                    from_=from_number,
                    body=content,
                    status_callback=self.callback_url,
                )

                self.logger.info('Twilio message created using from_number')
            else:
                # Make a request using the messaging service sid.
                #    https://www.twilio.com/docs/messaging/services
                message = self._client.messages.create(
                    to=to,
                    messaging_service_sid=messaging_service_sid,
                    body=content,
                    status_callback=self.callback_url,
                )

                self.logger.info('Twilio message created using messaging_service_sid')

            self.logger.info('Twilio send SMS request for %s succeeded: %s', reference, message.sid)

            return message.sid
        except Exception as e:
            self.logger.error('Twilio send SMS request for %s failed', reference)
            raise e
        finally:
            elapsed_time = monotonic() - start_time
            self.logger.info(
                'Twilio send SMS request for %s  finished in %f',
                reference,
                elapsed_time,
            )

    def translate_delivery_status(
        self,
        twilio_delivery_status_message: str,
    ) -> dict:
        """
        Parses the base64 encoded delivery status message from Twilio and returns a dictionary.
        The dictionary contains the following keys:
        - record_status: the convereted twilio to notification platform status
        - reference: the message id of the twilio message
        - payload: the original payload from twilio
        https://github.com/department-of-veterans-affairs/vanotify-team/blob/master/Engineering/SPIKES/SMS-Delivery-Status.md#twilio-implementation-of-delivery-statuses
        """
        self.logger.info('Translating Twilio delivery status')
        self.logger.debug(twilio_delivery_status_message)

        if not twilio_delivery_status_message:
            raise ValueError('Twilio delivery status message is empty')

        decoded_msg = base64.b64decode(twilio_delivery_status_message).decode()

        parsed_dict = parse_qs(decoded_msg)

        twilio_delivery_status = parsed_dict['MessageStatus'][0]

        if twilio_delivery_status not in self.twilio_notify_status_map:
            value_error = f'Invalid Twilio delivery status:  {twilio_delivery_status}'
            raise ValueError(value_error)

        if 'ErrorCode' in parsed_dict and (
            twilio_delivery_status == 'failed' or twilio_delivery_status == 'undelivered'
        ):
            error_code = parsed_dict['ErrorCode'][0]

            if error_code in self.twilio_error_code_map:
                notify_delivery_status = self.twilio_error_code_map[error_code]
            else:
                notify_delivery_status = self.twilio_notify_status_map[twilio_delivery_status]
        else:
            notify_delivery_status = self.twilio_notify_status_map[twilio_delivery_status]

        translation = {
            'payload': decoded_msg,
            'reference': parsed_dict['MessageSid'][0],
            'record_status': notify_delivery_status,
        }

        self.logger.debug('Twilio delivery status translation: %s', translation)

        return translation

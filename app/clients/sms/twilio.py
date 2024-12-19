import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger
from monotonic import monotonic
from urllib.parse import parse_qs

from twilio.rest import Client
from twilio.rest.api.v2010.account.message import MessageInstance
from twilio.base.exceptions import TwilioRestException

from app.celery.exceptions import NonRetryableException
from app.clients.sms import SmsClient, SmsStatusRecord, UNABLE_TO_TRANSLATE
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TEMPORARY_FAILURE,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNDELIVERABLE,
    STATUS_REASON_UNREACHABLE,
    TWILIO_PROVIDER,
)
from app.exceptions import InvalidProviderException


# https://www.twilio.com/docs/messaging/api/message-resource#message-status-values
TWILIO_RESPONSE_MAP = {
    'accepted': NOTIFICATION_CREATED,
    'delivered': NOTIFICATION_DELIVERED,
    'failed': NOTIFICATION_PERMANENT_FAILURE,
    'queued': NOTIFICATION_SENDING,
    'received': NOTIFICATION_SENDING,
    'sending': NOTIFICATION_SENDING,
    'sent': NOTIFICATION_SENT,
    'undelivered': NOTIFICATION_PERMANENT_FAILURE,
}


@dataclass
class TwilioStatus:
    code: int | None
    status: str
    status_reason: str | None


def get_twilio_responses(status):
    return TWILIO_RESPONSE_MAP[status]


class TwilioSMSClient(SmsClient):
    RAW_DLR_DONE_DATE_FMT = '%y%m%d%H%M'

    twilio_error_code_map = {
        # 21268: 'Premium numbers are not permitted'
        '21268': TwilioStatus(21268, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        # 21408: 'Invalid region specified'
        '21408': TwilioStatus(21408, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '21610': TwilioStatus(21610, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        # 21612: 'Invalid to/from combo'
        '21612': TwilioStatus(21612, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '21614': TwilioStatus(21614, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '21617': TwilioStatus(21617, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        '21635': TwilioStatus(21635, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '30001': TwilioStatus(30001, NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        # 30002: 'Account suspended'
        '30002': TwilioStatus(30002, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        '30003': TwilioStatus(30003, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '30004': TwilioStatus(30004, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        '30005': TwilioStatus(30005, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '30006': TwilioStatus(30006, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '30007': TwilioStatus(30007, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        '30008': TwilioStatus(30008, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        # 30009: 'Missing inbound segment'
        '30009': TwilioStatus(30009, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        # 30010: 'Message price exceeds max price'
        '30010': TwilioStatus(30010, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        # 30024: 'Sender not provisioned by carrier'
        '30024': TwilioStatus(30024, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        # 30034: 'Used an unregistered 10DLC Number'
        '30034': TwilioStatus(30034, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        '30442': TwilioStatus(30442, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        '30500': TwilioStatus(30500, NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        '30884': TwilioStatus(30884, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        '32017': TwilioStatus(32017, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        '32203': TwilioStatus(32203, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        '60005': TwilioStatus(60005, NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        '63026': TwilioStatus(63026, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
    }

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
        self.logger: Logger = None
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._client = Client(account_sid, auth_token)

        self.twilio_notify_status_map = {
            'accepted': TwilioStatus(None, NOTIFICATION_SENDING, None),
            'scheduled': TwilioStatus(None, NOTIFICATION_SENDING, None),
            'queued': TwilioStatus(None, NOTIFICATION_SENDING, None),
            'sending': TwilioStatus(None, NOTIFICATION_SENDING, None),
            'sent': TwilioStatus(None, NOTIFICATION_SENT, None),
            'delivered': TwilioStatus(None, NOTIFICATION_DELIVERED, None),
            'undelivered': TwilioStatus(None, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
            'failed': TwilioStatus(None, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
            'canceled': TwilioStatus(None, NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
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
        return TWILIO_PROVIDER

    def get_name(self):
        return self.name

    def get_twilio_message(self, message_sid: str) -> MessageInstance | None:
        """
        Fetches a Twilio message by its message sid.

        Args:
            message_sid (str): the Twilio message id

        Returns:
            MessageInstance: the Twilio message instance if found, otherwise None
        """
        message = None
        try:
            message = self._client.messages(message_sid).fetch()
        except TwilioRestException as e:
            self.logger.exception('Twilio message not found: %s', message_sid)
            if e.status == 429:
                self.logger.exception('Twilio rate limit exceeded')
                raise NonRetryableException('Twilio rate limit exceeded') from e
        return message

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
        from app.dao.service_sms_sender_dao import (
            dao_get_service_sms_sender_by_service_id_and_number,
            dao_get_service_sms_sender_by_id,
        )

        try:
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

                self.logger.info('Twilio message created using number: %s', from_number)
            else:
                # Make a request using the messaging service sid.
                #    https://www.twilio.com/docs/messaging/services
                message = self._client.messages.create(
                    to=to,
                    messaging_service_sid=messaging_service_sid,
                    body=content,
                    status_callback=self.callback_url,
                )

                self.logger.info('Twilio message created using messaging_service_sid: %s', messaging_service_sid)

            self.logger.info('Twilio send SMS request for %s succeeded: %s', reference, message.sid)

            return message.sid
        except TwilioRestException as e:
            if e.status == 400 and 'phone number' in e.msg:
                self.logger.exception('Twilio send SMS request for %s failed', reference)
                raise InvalidProviderException from e
            elif e.status == 400 and e.code == 21617:  # Twilio error code for max length exceeded
                status = self.twilio_error_code_map.get('21617')
                self.logger.exception(
                    'Twilio send SMS request for %s failed, message content length exceeded.', reference
                )
                self.logger.debug('Twilio error details for %s - %s: %s', reference, e.code, e.msg)
                raise NonRetryableException(status.status_reason) from e
            else:
                raise
        except:
            self.logger.exception('Twilio send SMS request for %s failed', reference)
            raise
        finally:
            elapsed_time = monotonic() - start_time
            self.logger.info(
                'Twilio send SMS request for %s  finished in %f',
                reference,
                elapsed_time,
            )

    def translate_delivery_status(
        self,
        delivery_status_message: str | dict[str, str],
    ) -> SmsStatusRecord:
        """
        Parses the base64 encoded delivery status message from Twilio and returns a dictionary.
        The dictionary contains the following keys:
        - record_status: the convereted twilio to notification platform status
        - reference: the message id of the twilio message
        - payload: the original payload from twilio
        https://github.com/department-of-veterans-affairs/vanotify-team/blob/main/Engineering/SPIKES/SMS-Delivery-Status.md#twilio-implementation-of-delivery-statuses
        """
        if not isinstance(delivery_status_message, str):
            self.logger.error('Did not receive twilio delivery status as a string')
            raise NonRetryableException(f'Incorrect datatype sent to twilio, {UNABLE_TO_TRANSLATE}')

        decoded_msg, parsed_dict = self._parse_twilio_message(delivery_status_message)
        message_sid = parsed_dict['MessageSid'][0]
        twilio_delivery_status = parsed_dict['MessageStatus'][0]
        error_code = parsed_dict.get('ErrorCode', [])
        status, status_reason = self._evaluate_status(message_sid, twilio_delivery_status, error_code)
        raw_dlr_done_date_list = parsed_dict.get('RawDlrDoneDate', [])
        provider_updated_at = (
            self._translate_raw_dlr_done_date(raw_dlr_done_date_list[0]) if raw_dlr_done_date_list else None
        )
        return SmsStatusRecord(
            decoded_msg,
            message_sid,
            status,
            status_reason,
            TWILIO_PROVIDER,
            provider_updated_at=provider_updated_at,
        )

    def _translate_raw_dlr_done_date(self, done_date: str) -> datetime:
        """Translate RawDlrDoneDate into a timezone unaware datetime object.

        Args:
            done_date (str): The incoming RawDlrDoneDate

        Returns:
            datetime: Time that Twilio received this update from the carrier
        """
        try:
            done_datetime = datetime.strptime(done_date, TwilioSMSClient.RAW_DLR_DONE_DATE_FMT)
        except ValueError:
            self.logger.exception('RawDlrDoneDate from twilio came in an unexpected format')
            done_datetime = datetime.now(timezone.utc).replace(tzinfo=None)
        return done_datetime

    def update_notification_status_override(self, message_sid: str) -> None:
        """
        Updates the status of the notification based on the Twilio message status, bypassing any logic.

        Args:
            message_sid (str): the Twilio message id

        Returns:
            None
        """
        # Importing inline to resolve a circular import error when importing at the top of the file
        from app.dao.notifications_dao import dao_update_notifications_by_reference

        self.logger.info('Updating notification status for message: %s', message_sid)

        message = self.get_twilio_message(message_sid)

        if message:
            status, status_reason = self._evaluate_status(message_sid, message.status, [])
            update_dict = {
                'status': status,
                'status_reason': status_reason,
            }
            updated_count, updated_history_count = dao_update_notifications_by_reference(
                [
                    message_sid,
                ],
                update_dict,
            )
            self.logger.info(
                'Updated notification status for message: %s to %s. Updated %s notifications and %s notification history',
                message_sid,
                status,
                updated_count,
                updated_history_count,
            )

    def _parse_twilio_message(self, twilio_delivery_status_message: MessageInstance) -> tuple[str, dict]:
        """
        Parses the base64 encoded delivery status message from Twilio and returns a dictionary.

        Args:
            twilio_delivery_status_message (str): the base64 encoded Twilio delivery status message

        Returns:
            tuple: a tuple containing the decoded message and a dictionary of the parsed message

        Raises:
            ValueError: if the Twilio delivery status message is empty
        """
        if not twilio_delivery_status_message:
            raise ValueError('Twilio delivery status message is empty')

        decoded_msg = base64.b64decode(twilio_delivery_status_message).decode()
        parsed_dict = parse_qs(decoded_msg)

        return decoded_msg, parsed_dict

    def _evaluate_status(self, message_sid: str, twilio_delivery_status: str, error_codes: list) -> tuple[str, str]:
        """
        Evaluates the Twilio delivery status and error codes to determine the notification status.

        Args:
            message_sid (str): the Twilio message id
            twilio_delivery_status (str): the Twilio message status
            error_codes (list): the Twilio error codes

        Returns:
            tuple: a tuple containing the notification status and status reason

        Raises:
            ValueError: if the Twilio delivery status is invalid
        """
        if twilio_delivery_status not in self.twilio_notify_status_map:
            value_error = f'Invalid Twilio delivery status:  {twilio_delivery_status}'
            raise ValueError(value_error)

        if error_codes and (twilio_delivery_status == 'failed' or twilio_delivery_status == 'undelivered'):
            error_code = error_codes[0]

            if error_code in self.twilio_error_code_map:
                notify_delivery_status: TwilioStatus = self.twilio_error_code_map[error_code]
            else:
                self.logger.warning(
                    'Unaccounted for Twilio Error code: %s with message sid: %s', error_code, message_sid
                )
                notify_delivery_status: TwilioStatus = self.twilio_notify_status_map[twilio_delivery_status]
        else:
            # Error codes may be retained for new messages, meaning a "sending" could retain a 30005
            if error_codes:
                self.logger.info(
                    'Error code: %s existed but status for message: %s with status: %s',
                    error_codes[0],
                    message_sid,
                    twilio_delivery_status,
                )
            notify_delivery_status: TwilioStatus = self.twilio_notify_status_map[twilio_delivery_status]

        return notify_delivery_status.status, notify_delivery_status.status_reason

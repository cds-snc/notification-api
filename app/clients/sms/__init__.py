from dataclasses import dataclass
from datetime import datetime

from app.clients import Client, ClientException

BLOCKED_MESSAGE = 'The message has been blocked'
MESSAGE_TOO_LONG = 'Message too long'
OPT_OUT_MESSAGE = 'The individual has opted out'
PRICE_THRESHOLD_EXCEEDED = 'Price threshold exceeded'
REPORTED_AS_SPAM = 'The message has been reported as spam'
RETRYABLE_AWS_RESPONSE = 'Encountered a temporary failure. Send the request to VA Notify again'
UNABLE_TO_TRANSLATE = 'unable to translate delivery status'
UNEXPECTED_PROVIDER_RESULT = 'Unexpected result'


class SmsClientResponseException(ClientException):
    """
    Base Exception for SmsClientsResponses
    """

    def __init__(
        self,
        message,
    ):
        self.message = message

    def __str__(self):
        return 'Message {}'.format(self.message)


@dataclass
class SmsStatusRecord:
    payload: str | dict[str, str] | None
    reference: str
    status: str
    status_reason: str | None
    provider: str
    message_parts: int = 1
    price_millicents: float = 0.0
    provider_updated_at: datetime | None = None


class SmsClient(Client):
    """
    Base Sms client for sending smss.
    """

    def send_sms(
        self,
        *args,
        **kwargs,
    ):
        raise NotImplementedError('TODO Need to implement.')

    # TODO: refactor to use property instead of manual getter
    def get_name(self):
        raise NotImplementedError('TODO Need to implement.')

    def translate_delivery_status(self, delivery_status_message: str | dict[str, str]) -> SmsStatusRecord:
        raise NotImplementedError('TODO Need to implement.')

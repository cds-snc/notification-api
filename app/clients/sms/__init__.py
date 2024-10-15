from dataclasses import dataclass

from app.clients import Client, ClientException


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
    payload: str
    reference: str
    status: str
    status_reason: str | None
    message_parts: int = 1
    price_millicents: float = 0.0


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

    def translate_delivery_status(self) -> SmsStatusRecord:
        raise NotImplementedError('TODO Need to implement.')

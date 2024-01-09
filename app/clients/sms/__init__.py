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

    def translate_delivery_status(self) -> dict:
        raise NotImplementedError('TODO Need to implement.')

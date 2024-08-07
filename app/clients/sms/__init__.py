from enum import Enum

from app.clients import Client, ClientException


class SmsSendingVehicles(Enum):
    SHORT_CODE = "short_code"
    LONG_CODE = "long_code"


class SmsClientResponseException(ClientException):
    """
    Base Exception for SmsClientsResponses
    """

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return "Message {}".format(self.message)


class SmsClient(Client):
    """
    Base Sms client for sending smss.
    """

    def send_sms(self, *args, **kwargs):
        raise NotImplementedError("TODO Need to implement.")

    def get_name(self):
        raise NotImplementedError("TODO Need to implement.")

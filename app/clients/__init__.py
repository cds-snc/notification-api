from typing import Any, Dict


class ClientException(Exception):
    """
    Base Exceptions for sending notifications that fail
    """

    pass


class Client(object):
    """
    Base client for sending notifications.
    """

    pass


class Clients(object):
    def __init__(self) -> None:
        self.sms_clients: Dict[str, Any] = {}
        self.email_clients: Dict[str, Any] = {}

    def init_app(self, sms_clients, email_clients):
        # Build new dicts and assign atomically so concurrent readers
        # never encounter a partially populated registry.
        self.sms_clients = {client.name: client for client in sms_clients}
        self.email_clients = {client.name: client for client in email_clients}

    def get_sms_client(self, name):
        return self.sms_clients.get(name)

    def get_email_client(self, name):
        return self.email_clients.get(name)

    def get_client_by_name_and_type(self, name, notification_type):
        assert notification_type in ["email", "sms"]

        if notification_type == "email":
            return self.get_email_client(name)

        if notification_type == "sms":
            return self.get_sms_client(name)

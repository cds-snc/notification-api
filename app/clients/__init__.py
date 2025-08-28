class ClientException(Exception):
    """
    Base Exceptions for sending notifications that fail.
    """

    pass


class Client:
    """
    Base client for sending notifications.
    """

    pass


STATISTICS_REQUESTED = 'requested'
STATISTICS_DELIVERED = 'delivered'
STATISTICS_FAILURE = 'failure'


class Clients:
    sms_clients = {}
    email_clients = {}

    def init_app(
        self,
        sms_clients,
        email_clients,
    ):
        for client in sms_clients:
            assert isinstance(client, Client)
            self.sms_clients[client.name] = client

        for client in email_clients:
            assert isinstance(client, Client)
            self.email_clients[client.name] = client

    def get_sms_client(
        self,
        name,
    ):
        return self.sms_clients.get(name)

    def get_email_client(
        self,
        name,
    ):
        return self.email_clients.get(name)

    def get_client_by_name_and_type(
        self,
        name,
        notification_type,
    ) -> Client | None:
        if notification_type == 'email':
            return self.get_email_client(name)
        elif notification_type == 'sms':
            return self.get_sms_client(name)

        raise ValueError(f'Unrecognized notification type: {notification_type}')

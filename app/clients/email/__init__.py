from app.clients import ClientException, Client


class EmailClientException(ClientException):
    '''
    Base Exception for EmailClients
    '''
    pass


class EmailClient(Client):
    '''
    Base Email client for sending emails.
    '''

    def send_email(self, *args, **kwargs):
        raise NotImplementedError('TODO Need to implement.')

    def get_name(self):
        raise NotImplementedError('TODO Need to implement.')

    @property
    def email_from_domain(self):
        '''
        Returns None by default.
        Can be overriden by child class if desired
        '''
        pass

    @property
    def email_from_user(self):
        '''
        Returns None by default.
        Can be overriden by child class if desired
        '''
        pass

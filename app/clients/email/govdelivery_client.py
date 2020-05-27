from app.clients.email import EmailClient


class GovdeliveryClient(EmailClient):
    '''
    Govdelivery email client.
    '''

    def init_app(self, statsd_client, *args, **kwargs):
        self.name = 'govdelivery'
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_email(self,
                   source,
                   to_addresses,
                   subject,
                   body,
                   html_body='',
                   reply_to_address=None,
                   attachments=[]):
        pass

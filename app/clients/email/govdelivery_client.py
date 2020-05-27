import requests

from app.clients.email import EmailClient


class GovdeliveryClient(EmailClient):
    '''
    Govdelivery email client.
    '''

    def init_app(self, token, statsd_client, *args, **kwargs):
        self.name = 'govdelivery'
        self.token = token
        self.statsd_client = statsd_client
        self.govdelivery_url = "https://tms.govdelivery.com/messages/email"

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
        if isinstance(to_addresses, str):
            to_addresses = [to_addresses]

        # Sometimes the source is "Foo <foo@bar.com> vs just foo@bar.com"
        # TODO: Possibly revisit this to take in sender name and sender email address separately
        if "<" in source:
            source = source.split("<")[1].split(">")[0]

        recipients = [
            {"email": to_address} for to_address in to_addresses
        ]

        payload = {
            "subject": subject,
            "body": body,
            "recipients": recipients,
            "from_email": source
        }

        response = requests.post(
            self.govdelivery_url,
            json=payload,
            headers={
                "X-AUTH-TOKEN": self.token
            }
        )

        return response

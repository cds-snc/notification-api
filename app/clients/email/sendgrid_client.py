from flask import current_app
from time import monotonic
from sendgrid import SendGridAPIClient

from app.clients.email import (EmailClientException, EmailClient)

sendgrid_response_map = {
    'processed': 'created',
    'deferred': 'deferred',
    'delivered': 'sent',
    'bounce': 'permanent-failure',
    'dropped': 'technical-failure',
}


def get_sendgrid_responses(status):
    return sendgrid_response_map[status]


class SendGridClientException(EmailClientException):
    pass


class SendGridClient(EmailClient):
    '''
    SendGrid email client.
    '''

    def init_app(self, key, statsd_client, *args, **kwargs):
        self._client = SendGridAPIClient(key)
        super(SendGridClient, self).__init__(*args, **kwargs)
        self.name = 'sendgrid'
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
        try:
            # Sometimes the source is "Foo <foo@bar.com> vs just foo@bar.com"
            if "<" in source:
                source = source.split("<")[1].split(">")[0]

            data = {
                "content": [
                    {
                        "type": "text/plain",
                        "value": body
                    },
                    {
                        "type": "text/html",
                        "value": html_body
                    }
                ],
                "personalizations": [
                    {
                        "to": [
                            {
                                "email": to_addresses
                            }
                        ],
                        "subject": str(subject)
                    }
                ],
                "from": {
                    "email": source
                }
            }

            if reply_to_address:
                data["reply_to"] = reply_to_address

            start_time = monotonic()
            response = self._client.client.mail.send.post(request_body=data)

        except Exception as e:
            self.statsd_client.incr("clients.sendgrid.error")
            raise SendGridClientException(str(e))
        else:
            elapsed_time = monotonic() - start_time
            current_app.logger.info("Send_Grid request finished in {}".format(elapsed_time))
            self.statsd_client.timing("clients.sendgrid.request-time", elapsed_time)
            self.statsd_client.incr("clients.sendgrid.success")
            return response.headers["X-Message-Id"]


def punycode_encode_email(email_address):
    # only the hostname should ever be punycode encoded.
    local, hostname = email_address.split('@')
    return '{}@{}'.format(local, hostname.encode('idna').decode('utf-8'))

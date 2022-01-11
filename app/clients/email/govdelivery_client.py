from app.models import (NOTIFICATION_CANCELLED, NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE,
                        NOTIFICATION_SENDING, NOTIFICATION_TEMPORARY_FAILURE)
from time import monotonic

import requests
from flask import current_app
from notifications_utils.recipients import InvalidEmailError
from requests import HTTPError

from app.clients.email import EmailClient, EmailClientException

govdelivery_status_map = {
    'sending': NOTIFICATION_SENDING,
    'sent': NOTIFICATION_DELIVERED,
    'blacklisted': NOTIFICATION_PERMANENT_FAILURE,
    'canceled': NOTIFICATION_CANCELLED,
    'failed': NOTIFICATION_PERMANENT_FAILURE,
    'inconclusive': NOTIFICATION_TEMPORARY_FAILURE,
}


class GovdeliveryClientException(EmailClientException):
    pass


class GovdeliveryClient(EmailClient):
    '''
    Govdelivery email client.
    '''

    def init_app(self, token, url, statsd_client, *args, **kwargs):
        self.name = 'govdelivery'
        self.token = token
        self.statsd_client = statsd_client
        self.govdelivery_url = "{}/messages/email".format(url)

    def get_name(self):
        return self.name

    def send_email(self,
                   source,
                   to_addresses,
                   subject,
                   body,
                   html_body,
                   reply_to_address=None,
                   attachments=[]):
        try:
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
                "body": html_body,
                "recipients": recipients,
                "from_email": source,
                "click_tracking_enabled": False
            }

            start_time = monotonic()
            response = requests.post(
                self.govdelivery_url,
                json=payload,
                headers={
                    "X-AUTH-TOKEN": self.token
                }
            )
            response.raise_for_status()

        except HTTPError as e:
            self.statsd_client.incr("clients.govdelivery.error")
            if e.response.status_code == 422:
                raise InvalidEmailError(str(e))
            else:
                raise GovdeliveryClientException(str(e))
        except Exception as e:
            self.statsd_client.incr("clients.govdelivery.error")
            raise GovdeliveryClientException(str(e))
        else:
            elapsed_time = monotonic() - start_time
            current_app.logger.info("Govdelivery request finished in {}".format(elapsed_time))
            self.statsd_client.timing("clients.govdelivery.request-time", elapsed_time)
            self.statsd_client.incr("clients.govdelivery.success")
            return response.json()["id"]

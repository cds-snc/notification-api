import requests
from flask import current_app


class VAProfileClient:
    #
    # def __init__(
    #         self
    # ):
    #     pass

    def init_app(self, va_profile_url):
        self.va_profile_url = va_profile_url

    def get_email(self, va_profile_id):
        current_app.logger.info("Querying VA Profile with ID " + va_profile_id)

        requests.get(f"{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/emails")

        # parse the response

        # extract the email address

        return "test@test.com"


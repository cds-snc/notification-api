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

        response = requests.get(
            f"{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/emails",
            cert=(current_app.config['VANOTIFY_SSL_CERT_PATH'], current_app.config['VANOTIFY_SSL_KEY_PATH'])
        )
        return self._parse_response(response)

    def _parse_response(self, response_text):
        response_dict = response_text.json()
        if response_dict['status'] == 'COMPLETED_SUCCESS':
            return response_dict['bios'][0]['emailAddressText']

import requests


class VAProfileClientException(Exception):
    pass


class VAProfileClient:

    def init_app(self, logger, va_profile_url, ssl_cert_path, ssl_key_path):
        self.logger = logger
        self.va_profile_url = va_profile_url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path

    def get_email(self, va_profile_id):
        self.logger.info("Querying VA Profile with ID " + va_profile_id)

        response = requests.get(
            f"{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/emails",
            cert=(self.ssl_cert_path, self.ssl_key_path)
        )

        if response.status_code != 200:
            raise VAProfileClientException(f"VA Profile responded with HTTP {response.status_code}")

        return self._parse_response(response)

    def _parse_response(self, response):
        response_json = response.json()

        if response_json['status'] != 'COMPLETED_SUCCESS':
            raise VAProfileClientException(f"VA Profile responded with status {response_json['status']}")

        email_address_text = self._fetch_email_from_bios(response_json)
        self.logger.info(f"Did VAProfile send email address? {email_address_text is not None}")
        return email_address_text

    def _fetch_email_from_bios(self, response_json):
        try:
            return response_json['bios'][0]['emailAddressText']
        except KeyError as e:
            raise VAProfileClientException("No email in VA Profile response") from e

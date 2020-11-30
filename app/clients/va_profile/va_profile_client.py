import requests


class VAProfileClientException(Exception):
    pass


class VAProfileClient:
    #
    # def __init__(
    #         self
    # ):
    #     pass

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
        return self._parse_response(response)

    def _parse_response(self, response):
        if response.status_code == 200:
            response_dict = response.json()
            if response_dict['status'] == 'COMPLETED_SUCCESS':
                email_address_text = self._fetch_email_from_bios(response_dict)
                self.logger.info(f"Did VAProfile send email address? {email_address_text is not None}")
                return email_address_text

    def _fetch_email_from_bios(self, response_dict):
        bios = response_dict.get('bios')
        if bios and len(bios) > 0:
            return bios[0]['emailAddressText']
        else:
            raise VAProfileClientException("No email in VA Profile response")

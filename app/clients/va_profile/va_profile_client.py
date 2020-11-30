import requests
import iso8601


class VAProfileException(Exception):
    pass


class VAProfileClient:

    SUCCESS_STATUS = 'COMPLETED_SUCCESS'

    def init_app(self, logger, va_profile_url, ssl_cert_path, ssl_key_path):
        self.logger = logger
        self.va_profile_url = va_profile_url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path

    def get_email(self, va_profile_id):
        self.logger.info(f"Querying VA Profile with ID {va_profile_id}")
        response = self._make_request(va_profile_id)

        try:
            most_recently_created_bio = self._get_most_recently_created_bio(response)
            return most_recently_created_bio['emailAddressText']
        except KeyError as e:
            raise VAProfileException(f"No email in response for VA Profile ID {va_profile_id}") from e

    def _make_request(self, va_profile_id):
        response = requests.get(
            f"{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/emails",
            cert=(self.ssl_cert_path, self.ssl_key_path)
        )
        response.raise_for_status()

        response_status = response.json()['status']
        if response_status != self.SUCCESS_STATUS:
            raise VAProfileException(f"Response status was {response_status} for VA Profile ID {va_profile_id}")

        return response

    def _get_most_recently_created_bio(self, response):
        sorted_bios = sorted(
            response.json()['bios'],
            key=lambda bio: iso8601.parse_date(bio['createDate']),
            reverse=True
        )
        return sorted_bios[0]

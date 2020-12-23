from enum import Enum

import requests
import iso8601
from time import monotonic

from app.va.va_profile import (
    NoContactInfoException,
    VAProfileNonRetryableException,
    VAProfileRetryableException
)


class PhoneNumberType(Enum):

    MOBILE = 'MOBILE'
    HOME = 'HOME'
    WORK = 'WORK'
    FAX = 'FAX'
    TEMPORARY = 'TEMPORARY'

    @staticmethod
    def valid_type_values():
        return [PhoneNumberType.MOBILE.value, PhoneNumberType.HOME.value]

    @staticmethod
    def invalid_type_values():
        return [PhoneNumberType.WORK.value, PhoneNumberType.FAX.value, PhoneNumberType.TEMPORARY.value]


class VAProfileClient:

    SUCCESS_STATUS = 'COMPLETED_SUCCESS'

    def init_app(self, logger, va_profile_url, ssl_cert_path, ssl_key_path, statsd_client):
        self.logger = logger
        self.va_profile_url = va_profile_url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.statsd_client = statsd_client

    def get_email(self, va_profile_id):
        self.logger.info(f"Querying VA Profile with ID {va_profile_id}")
        response = self._make_request(va_profile_id, 'emails')

        try:
            most_recently_created_bio = self._get_most_recently_created_bio(response)
            self.statsd_client.incr("clients.va-profile.get-email.success")
            return most_recently_created_bio['emailAddressText']
        except KeyError as e:
            self.statsd_client.incr("clients.va-profile.get-email.error")
            raise NoContactInfoException(f"No email in response for VA Profile ID {va_profile_id}") from e

    def get_telephone(self, va_profile_id):
        self.logger.info(f"Querying VA Profile with ID {va_profile_id}")
        response = self._make_request(va_profile_id, 'telephones')

        try:
            phone_number = self._get_mobile_number(response)
            if phone_number is None:
                self.statsd_client.incr("clients.va-profile.get-telephone.no-phone-number")
                raise NoContactInfoException(
                    f"No {PhoneNumberType.valid_type_values()} in response for VA Profile ID {va_profile_id}")

            self.statsd_client.incr("clients.va-profile.get-telephone.success")
            return phone_number
        except KeyError as e:
            self.statsd_client.incr("clients.va-profile.get-telephone.error")
            raise NoContactInfoException(f"No telephone in response for VA Profile ID {va_profile_id}") from e

    def _make_request(self, va_profile_id, bio_type):
        start_time = monotonic()
        try:
            response = requests.get(
                f"{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/{bio_type}",
                cert=(self.ssl_cert_path, self.ssl_key_path)
            )
            response.raise_for_status()

        except requests.HTTPError as e:
            self.logger.exception(e)
            self.statsd_client.incr(f"clients.va-profile.error.{e.response.status_code}")
            if e.response.status_code in [429, 500, 502, 503, 504]:
                raise VAProfileRetryableException(str(e)) from e
            else:
                raise VAProfileNonRetryableException(str(e)) from e

        except requests.RequestException as e:
            self.statsd_client.incr(f"clients.va-profile.error.request_exception")
            raise VAProfileRetryableException(f"VA Profile returned {str(e)} while querying for VA Profile ID") from e

        else:
            response_status = response.json()['status']
            if response_status != self.SUCCESS_STATUS:
                self.statsd_client.incr(f"clients.va-profile.error.{response_status}")
                raise VAProfileNonRetryableException(
                    f"Response status was {response_status} for VA Profile ID {va_profile_id}"
                )

            self.statsd_client.incr("clients.va-profile.success")
            return response

        finally:
            elapsed_time = monotonic() - start_time
            self.statsd_client.timing("clients.va-profile.request-time", elapsed_time)

    @staticmethod
    def _get_most_recently_created_bio(response):
        sorted_bios = sorted(
            response.json()['bios'],
            key=lambda bio: iso8601.parse_date(bio['createDate']),
            reverse=True
        )
        return sorted_bios[0]

    @staticmethod
    def _get_mobile_number(response):
        phone_number = None
        sorted_bios = sorted(
            list(filter(
                lambda bio:
                bio['phoneType'] in PhoneNumberType.valid_type_values(),
                response.json()['bios']
            )),
            key=lambda bio: iso8601.parse_date(bio['createDate']),
            reverse=True
        )

        if len(sorted_bios) > 0:
            phone_number =\
                f"+{sorted_bios[0]['countryCode']}{sorted_bios[0]['areaCode']}{sorted_bios[0]['phoneNumber']}"

        return phone_number

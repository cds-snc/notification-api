from enum import Enum

import requests
import iso8601
from time import monotonic
from http.client import responses

from app.va.va_profile import (
    NoContactInfoException,
    VAProfileNonRetryableException,
    VAProfileRetryableException
)
from app.va.identifier import is_fhir_format, transform_from_fhir_format


class PhoneNumberType(Enum):

    MOBILE = 'MOBILE'
    HOME = 'HOME'
    WORK = 'WORK'
    FAX = 'FAX'
    TEMPORARY = 'TEMPORARY'

    @staticmethod
    def valid_type_values():
        return [PhoneNumberType.MOBILE.value, PhoneNumberType.HOME.value]


class VAProfileClient:

    SUCCESS_STATUS = 'COMPLETED_SUCCESS'
    EMAIL_BIO_TYPE = 'emails'
    PHONE_BIO_TYPE = 'telephones'
    TX_AUDIT_ID = 'txAuditId'

    def init_app(self, logger, va_profile_url, ssl_cert_path, ssl_key_path, statsd_client):
        self.logger = logger
        self.va_profile_url = va_profile_url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.statsd_client = statsd_client

    def get_email(self, va_profile_id):
        response = self._make_request(va_profile_id, self.EMAIL_BIO_TYPE)

        most_recently_created_bio = self._get_most_recently_created_email_bio(response, va_profile_id)
        email = most_recently_created_bio['emailAddressText']
        self.statsd_client.incr("clients.va-profile.get-email.success")
        return email

    def get_telephone(self, va_profile_id):
        response = self._make_request(va_profile_id, self.PHONE_BIO_TYPE)

        most_recently_created_bio = self._get_highest_order_phone_bio(response, va_profile_id)
        phone_number = f"+{most_recently_created_bio['countryCode']}" \
                       f"{most_recently_created_bio['areaCode']}" \
                       f"{most_recently_created_bio['phoneNumber']}"
        self.statsd_client.incr("clients.va-profile.get-telephone.success")
        return phone_number

    def _make_request(self, va_profile_id, bio_type):
        start_time = monotonic()

        if is_fhir_format(va_profile_id):
            va_profile_id = transform_from_fhir_format(va_profile_id)

        self.logger.info(f"Querying VA Profile with ID {va_profile_id}")

        try:
            response = requests.get(
                f"{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/{bio_type}",
                cert=(self.ssl_cert_path, self.ssl_key_path)
            )
            response.raise_for_status()

        except requests.HTTPError as e:
            self.logger.exception(e)
            self.statsd_client.incr(f"clients.va-profile.error.{e.response.status_code}")

            failure_reason = (
                f'Received {responses[e.response.status_code]} HTTP error ({e.response.status_code}) while making a '
                'request to obtain contact info from VA Profile'
            )

            if e.response.status_code in [429, 500, 502, 503, 504]:
                exception = VAProfileRetryableException(str(e))
                exception.failure_reason = failure_reason

                raise exception from e
            else:
                exception = VAProfileNonRetryableException(str(e))
                exception.failure_reason = failure_reason

                raise exception from e

        except requests.RequestException as e:
            self.statsd_client.incr(f"clients.va-profile.error.request_exception")

            failure_message = f'VA Profile returned RequestException while querying for VA Profile ID'

            exception = VAProfileRetryableException(failure_message)
            exception.failure_reason = failure_message

            raise exception from e

        else:
            response_json = response.json()
            response_status = response_json['status']
            if response_status != self.SUCCESS_STATUS:
                self.statsd_client.incr(f"clients.va-profile.error.{response_status}")

                message = (
                    f'Response status was {response_status} for VA Profile ID {va_profile_id} '
                    f'with AuditId {response_json.get(self.TX_AUDIT_ID)}'
                )

                exception = VAProfileNonRetryableException(message)
                exception.failure_reason = message
                raise exception
            self._validate_response(response_json, va_profile_id, bio_type)

            self.statsd_client.incr("clients.va-profile.success")
            return response_json

        finally:
            elapsed_time = monotonic() - start_time
            self.statsd_client.timing("clients.va-profile.request-time", elapsed_time)

    def _get_most_recently_created_email_bio(self, response, va_profile_id):
        sorted_bios = sorted(
            response['bios'],
            key=lambda bio: iso8601.parse_date(bio['createDate']),
            reverse=True
        )
        return sorted_bios[0] if sorted_bios else \
            self._raise_no_contact_info_exception(self.EMAIL_BIO_TYPE, va_profile_id, response.get(self.TX_AUDIT_ID))

    def _get_highest_order_phone_bio(self, response, va_profile_id):
        # First sort by phone type and then by create date
        # since reverse order is used, potential MOBILE bios will end up before HOME
        sorted_bios = sorted(
            (bio for bio in response['bios'] if bio['phoneType'] in PhoneNumberType.valid_type_values()),
            key=lambda bio: (bio['phoneType'], iso8601.parse_date(bio['createDate'])),
            reverse=True
        )
        return sorted_bios[0] if sorted_bios else \
            self._raise_no_contact_info_exception(self.PHONE_BIO_TYPE, va_profile_id, response.get(self.TX_AUDIT_ID))

    def _raise_no_contact_info_exception(self, bio_type: str, va_profile_id: str, tx_audit_id: str):
        self.statsd_client.incr(f"clients.va-profile.get-{bio_type}.no-{bio_type}")
        raise NoContactInfoException(f"No {bio_type} in response for VA Profile ID {va_profile_id} "
                                     f"with AuditId {tx_audit_id}")

    def _validate_response(self, response, va_profile_id, bio_type):
        if response.get('messages'):
            self._raise_no_contact_info_exception(bio_type, va_profile_id, response.get(self.TX_AUDIT_ID))

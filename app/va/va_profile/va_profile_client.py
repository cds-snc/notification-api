from __future__ import annotations

import iso8601
import requests
from app.va.va_profile import (
    NoContactInfoException,
    VAProfileNonRetryableException,
    VAProfileRetryableException,
)
from app.va.identifier import is_fhir_format, transform_from_fhir_format, transform_to_fhir_format, OIDS, IdentifierType
from app.va.va_profile.exceptions import VAProfileIDNotFoundException
from enum import Enum
from http.client import responses
from time import monotonic
from typing import Dict, List, TYPE_CHECKING


if TYPE_CHECKING:
    from app.models import RecipientIdentifier
    from va_profile_types import ContactInformation, CommunicationPermissions, Profile, Telephone

EMAIL_TYPE = 'email'
LETTER_TYPE = 'letter'
MOBILE_TYPE = 'mobile'
PUSH_TYPE = 'push'
SMS_TYPE = 'sms'

VA_NOTIFY_TO_VA_PROFILE_NOTIFICATION_TYPES = {
    EMAIL_TYPE: 'Email',
    SMS_TYPE: 'Text',
}


class CommunicationItemNotFoundException(Exception):
    failure_reason = 'No communication bio found from VA Profile'


class PhoneNumberType(Enum):
    MOBILE = 'MOBILE'
    HOME = 'HOME'
    WORK = 'WORK'
    FAX = 'FAX'
    TEMPORARY = 'TEMPORARY'

    @staticmethod
    def valid_type_values() -> list[str]:
        return [PhoneNumberType.MOBILE.value, PhoneNumberType.HOME.value]


class VAProfileClient:
    SUCCESS_STATUS = 'COMPLETED_SUCCESS'
    EMAIL_BIO_TYPE = 'emails'
    PHONE_BIO_TYPE = 'telephones'
    TX_AUDIT_ID = 'txAuditId'

    def init_app(
        self,
        logger,
        va_profile_url,
        ssl_cert_path,
        ssl_key_path,
        va_profile_token,
        statsd_client,
    ):
        self.logger = logger
        self.va_profile_url = va_profile_url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.va_profile_token = va_profile_token
        self.statsd_client = statsd_client

    def get_profile(self, va_profile_id: RecipientIdentifier) -> Profile:
        """
        Retrieve the profile information for a given VA profile ID using the v3 API endpoint.

        Args:
            va_profile_id (RecipientIdentifier): The VA profile ID to retrieve the profile for.

        Returns:
            Profile: The profile information retrieved from the VA Profile service.
        """
        recipient_id = transform_to_fhir_format(va_profile_id)
        oid = OIDS.get(IdentifierType.VA_PROFILE_ID)
        url = f'{self.va_profile_url}/profile-service/profile/v3/{oid}/{recipient_id}'
        data = {'bios': [{'bioPath': 'contactInformation'}, {'bioPath': 'communicationPermissions'}]}

        try:
            response = requests.post(url, json=data, cert=(self.ssl_cert_path, self.ssl_key_path), timeout=(3.05, 1))
            response.raise_for_status()
        except (requests.HTTPError, requests.RequestException, requests.Timeout) as e:
            self._handle_exceptions(va_profile_id.id_value, e)

        response_json: Dict = response.json()
        return response_json.get('profile', {})

    def get_telephone_from_profile_v3(self, va_profile_id: RecipientIdentifier) -> str:
        """
        Retrieve the telephone number from the profile information for a given VA profile ID.

        Args:
            va_profile_id (RecipientIdentifier): The VA profile ID to retrieve the telephone number for.

        Returns:
            str: The telephone number retrieved from the VA Profile service.
        """
        contact_info: ContactInformation = self.get_profile(va_profile_id).get('contactInformation', {})
        self.logger.debug('V3 Profile - Retrieved ContactInformation: %s', contact_info)

        telephones: List[Telephone] = contact_info.get(self.PHONE_BIO_TYPE, [])
        phone_numbers = ', '.join([tel['phoneNumber'] for tel in telephones])
        self.logger.debug('V3 Profile telephones: %s', phone_numbers)
        sorted_telephones = sorted(
            [phone for phone in telephones if phone['phoneType'] == PhoneNumberType.MOBILE.value],
            key=lambda phone: iso8601.parse_date(phone['createDate']),
            reverse=True,
        )
        if sorted_telephones:
            if (
                sorted_telephones[0].get('countryCode')
                and sorted_telephones[0].get('areaCode')
                and sorted_telephones[0].get('phoneNumber')
            ):
                self.statsd_client.incr('clients.va-profile.get-telephone.success')
            return f"+{sorted_telephones[0]['countryCode']}{sorted_telephones[0]['areaCode']}{sorted_telephones[0]['phoneNumber']}"

        self.statsd_client.incr('clients.va-profile.get-telephone.failure')
        self._raise_no_contact_info_exception(self.PHONE_BIO_TYPE, va_profile_id, contact_info.get(self.TX_AUDIT_ID))

    def get_email_from_profile_v3(self, va_profile_id: RecipientIdentifier) -> str:
        """
        Retrieve the email address from the profile information for a given VA profile ID.

        Args:
            va_profile_id (RecipientIdentifier): The VA profile ID to retrieve the email address for.

        Returns:
            str: The email address retrieved from the VA Profile service.
        """
        contact_info: ContactInformation = self.get_profile(va_profile_id).get('contactInformation', {})
        sorted_emails = sorted(
            contact_info.get(self.EMAIL_BIO_TYPE, []),
            key=lambda email: iso8601.parse_date(email['createDate']),
            reverse=True,
        )
        if sorted_emails:
            self.statsd_client.incr('clients.va-profile.get-email.success')
            return sorted_emails[0].get('emailAddressText')

        self.statsd_client.incr('clients.va-profile.get-email.failure')
        self._raise_no_contact_info_exception(self.EMAIL_BIO_TYPE, va_profile_id, contact_info.get(self.TX_AUDIT_ID))

    def get_email(
        self,
        va_profile_id,
    ) -> str:
        """
        Return the e-mail address for a given Profile ID, or raise NoContactInfoException.
        Upstream code should catch and appropriately handle the requests.Timeout exception.
        """

        if is_fhir_format(va_profile_id):
            va_profile_id = transform_from_fhir_format(va_profile_id)

        url = (
            f'{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/'
            f'{va_profile_id}/{self.EMAIL_BIO_TYPE}'
        )
        response = self._make_request(url, va_profile_id, self.EMAIL_BIO_TYPE)

        try:
            sorted_bios = sorted(response['bios'], key=lambda bio: iso8601.parse_date(bio['createDate']), reverse=True)
            if sorted_bios:
                if sorted_bios[0].get('emailAddressText'):
                    # The e-mail address attribute is present and not the empty string.
                    self.statsd_client.incr('clients.va-profile.get-email.success')
                # This is intentionally allowed to raise KeyError so the problem is logged below.
                return sorted_bios[0]['emailAddressText']
        except KeyError as e:
            self.logger.error('Received a garbled response from VA Profile for ID %s.', va_profile_id)
            self.logger.exception(e)

        self.statsd_client.incr('clients.va-profile.get-email.failure')
        self._raise_no_contact_info_exception(self.EMAIL_BIO_TYPE, va_profile_id, response.get(self.TX_AUDIT_ID))

    def get_telephone(
        self,
        va_profile_id,
    ) -> str:
        """
        Return the phone number for a given Profile ID, or raise NoContactInfoException.
        Upstream code should catch and appropriately handle the requests.Timeout exception.
        """

        if is_fhir_format(va_profile_id):
            va_profile_id = transform_from_fhir_format(va_profile_id)

        url = (
            f'{self.va_profile_url}/contact-information-hub/cuf/contact-information/v1/'
            f'{va_profile_id}/{self.PHONE_BIO_TYPE}'
        )
        response = self._make_request(url, va_profile_id, self.PHONE_BIO_TYPE)

        try:
            # First sort by phone type and then by create date.  Since reverse order is used,
            # potential MOBILE bios will end up before HOME.
            sorted_bios = sorted(
                (bio for bio in response['bios'] if bio['phoneType'] in PhoneNumberType.valid_type_values()),
                key=lambda bio: (bio['phoneType'], iso8601.parse_date(bio['createDate'])),
                reverse=True,
            )
            if sorted_bios:
                if (
                    sorted_bios[0].get('countryCode')
                    and sorted_bios[0].get('areaCode')
                    and sorted_bios[0].get('phoneNumber')
                ):
                    # The required attributes are present and not empty strings.
                    self.statsd_client.incr('clients.va-profile.get-telephone.success')
                # This is intentionally allowed to raise KeyError so the problem is logged below.
                return '+' + sorted_bios[0]['countryCode'] + sorted_bios[0]['areaCode'] + sorted_bios[0]['phoneNumber']
        except KeyError as e:
            self.logger.error('Received a garbled response from VA Profile for ID %s.', va_profile_id)
            self.logger.exception(e)

        self.statsd_client.incr('clients.va-profile.get-telephone.failure')
        self._raise_no_contact_info_exception(self.PHONE_BIO_TYPE, va_profile_id, response.get(self.TX_AUDIT_ID))

    def get_is_communication_allowed_v3(
        self,
        recipient_id: RecipientIdentifier,
        communication_item_id: str,
        notification_id: str,
        notification_type: str,
    ) -> bool:
        """
        Determine if communication is allowed for a given recipient, communication item, and notification type.

        Args:
            recipient_id (RecipientIdentifier): The recipient's VA profile ID.
            communication_item_id (str): The ID of the communication item.
            notification_id (str): The ID of the notification.
            notification_type (str): The type of the notification.

        Returns:
            bool: True if communication is allowed, False otherwise.

        Raises:
            CommunicationItemNotFoundException: If no communication permissions are found for the given parameters.
        """

        communication_permissions: CommunicationPermissions = self.get_profile(recipient_id).get(
            'communicationPermissions', {}
        )
        self.logger.debug(
            'V3 Profile -- Retrieved Communication Permissions for recipient_id: %s, notification_id: \
              %s, notification_type: %s -- %s',
            recipient_id.id_value,
            notification_id,
            notification_type,
            communication_permissions,
        )
        for perm in communication_permissions:
            self.logger.debug(
                'V3 Profile -- Found communication item id %s on recipient %s for notification %s',
                communication_item_id,
                recipient_id.id_value,
                notification_id,
            )
            if (
                perm['communicationChannelName'] == VA_NOTIFY_TO_VA_PROFILE_NOTIFICATION_TYPES[notification_type]
                and perm['communicationItemId'] == communication_item_id
            ):
                self.logger.debug(
                    'V3 Profile -- %s notification:  Value of allowed is %s for notification %s',
                    perm['communicationChannelName'],
                    perm['allowed'],
                    notification_id,
                )
                self.statsd_client.incr('clients.va-profile.get-communication-item-permission.success')
                assert isinstance(perm['allowed'], bool)
                return perm['allowed']

        self.logger.debug(
            'V3 Profile -- Recipient %s did not have permission for communication item %s and channel %s for notification %s',
            recipient_id,
            communication_item_id,
            notification_type,
            notification_id,
        )

        # TODO 893 - use default communication item settings when that has been implemented
        self.statsd_client.incr('clients.va-profile.get-communication-item-permission.no-permissions')
        raise CommunicationItemNotFoundException

    def get_is_communication_allowed(
        self, recipient_identifier, communication_item_id: str, notification_id: str, notification_type: str
    ) -> bool:
        from app.models import VA_NOTIFY_TO_VA_PROFILE_NOTIFICATION_TYPES

        recipient_id = transform_to_fhir_format(recipient_identifier)
        identifier_type = IdentifierType(recipient_identifier.id_type)
        oid = OIDS.get(identifier_type)

        url = (
            f'{self.va_profile_url}/communication-hub/communication/v1/'
            f'{oid}/{recipient_id}/communication-permissions?communicationItemId={communication_item_id}'
        )
        self.logger.info(
            'VA Profile URL used for making request to get communication-permissions for notification %s: %s',
            notification_id,
            url,
        )
        response = self._make_request(url, recipient_id)
        self.logger.info(
            'Made request to communication-permissions VAProfile endpoint for recipient %s for notification %s',
            recipient_identifier,
            notification_id,
        )

        all_bios = response.get('bios', [])
        for bio in all_bios:
            self.logger.info(
                'Found communication item id %s on recipient %s for notification %s',
                communication_item_id,
                recipient_id,
                notification_id,
            )
            if bio['communicationChannelName'] == VA_NOTIFY_TO_VA_PROFILE_NOTIFICATION_TYPES[notification_type]:
                self.logger.info('Value of allowed is %s for notification %s', bio['allowed'], notification_id)
                self.statsd_client.incr('clients.va-profile.get-communication-item-permission.success')
                return bio['allowed'] is True

        self.logger.info(
            'Recipient %s did not have permission for communication item %s and channel %s for notification %s',
            recipient_id,
            communication_item_id,
            notification_type,
            notification_id,
        )

        # TODO 893 - use default communication item settings when that has been implemented
        self.statsd_client.incr('clients.va-profile.get-communication-item-permission.no-permissions')
        raise CommunicationItemNotFoundException

    def _handle_exceptions(self, va_profile_id_value: str, error: Exception):
        """
        Handle exceptions that occur during requests to the VA Profile service.

        Args:
            va_profile_id_value (str): The VA profile ID value associated with the request.
            error (Exception): The exception that was raised during the request.

        Raises:
            VAProfileRetryableException: If the error is a retryable HTTP error or a RequestException.
            VAProfileIDNotFoundException: If the error is a 404 HTTP error.
            VAProfileNonRetryableException: If the error is a non-retryable HTTP error.
            requests.Timeout: If the error is a Timeout exception.
        """
        if isinstance(error, requests.HTTPError):
            self.logger.warning(
                'HTTPError raised making request to VA Profile for VA Profile ID: %s', va_profile_id_value
            )
            self.statsd_client.incr(f'clients.va-profile.error.{error.response.status_code}')

            failure_reason = (
                f'Received {responses[error.response.status_code]} HTTP error ({error.response.status_code}) while making a '
                'request to obtain info from VA Profile'
            )

            if error.response.status_code in [429, 500, 502, 503, 504]:
                exception = VAProfileRetryableException(str(error))
                exception.failure_reason = failure_reason

                raise exception from error
            elif error.response.status_code == 404:
                exception = VAProfileIDNotFoundException(str(error))

                raise exception from error
            else:
                exception = VAProfileNonRetryableException(str(error))
                exception.failure_reason = failure_reason

                raise exception from error

        elif isinstance(error, requests.Timeout):
            self.logger.error('The request to VA Profile timed out for VA Profile ID %s.', va_profile_id_value)
            raise

        elif isinstance(error, requests.RequestException):
            self.statsd_client.incr('clients.va-profile.error.request_exception')

            failure_message = 'VA Profile returned RequestException while querying for VA Profile ID'

            exception = VAProfileRetryableException(failure_message)
            exception.failure_reason = failure_message

            raise exception from error

    def _make_request(
        self,
        url: str,
        va_profile_id: str,
        bio_type: str = None,
    ) -> dict:
        """
        Make a request to the VA Profile service and handle the response.

        Args:
            url (str): The URL to send the request to.
            va_profile_id (str): The VA profile ID associated with the request.
            bio_type (str, optional): The type of biographical data to validate in the response. Defaults to None.

        Returns:
            dict: The JSON response from the VA Profile service if the request is successful.

        Raises:
            VAProfileIDNotFoundException: If the response status is not successful or if the VA profile ID is not found.
            VAProfileRetryableException: If a retryable error occurs during the request.
            VAProfileNonRetryableException: If a non-retryable error occurs during the request.
            requests.Timeout: If the request times out.
        """
        start_time = monotonic()

        self.logger.info('Querying VA Profile with ID %s', va_profile_id)

        try:
            response = requests.get(url, cert=(self.ssl_cert_path, self.ssl_key_path), timeout=(3.05, 1))
            response.raise_for_status()

        except (requests.HTTPError, requests.RequestException, requests.Timeout) as e:
            self._handle_exceptions(va_profile_id, e)

        else:
            response_json = response.json()
            response_status = response_json['status']
            if response_status != self.SUCCESS_STATUS:
                self.statsd_client.incr(f'clients.va-profile.error.{response_status}')

                raise VAProfileIDNotFoundException

            if bio_type:
                self._validate_response(response_json, va_profile_id, bio_type)

            self.statsd_client.incr('clients.va-profile.success')
            return response_json

        finally:
            elapsed_time = monotonic() - start_time
            self.statsd_client.timing('clients.va-profile.request-time', elapsed_time)

    def _raise_no_contact_info_exception(
        self,
        bio_type: str,
        va_profile_id: str,
        tx_audit_id: str,
    ):
        self.statsd_client.incr(f'clients.va-profile.get-{bio_type}.no-{bio_type}')
        raise NoContactInfoException(
            f'No {bio_type} in response for VA Profile ID {va_profile_id} ' f'with AuditId {tx_audit_id}'
        )

    def _validate_response(
        self,
        response,
        va_profile_id,
        bio_type,
    ):
        if response.get('messages'):
            self._raise_no_contact_info_exception(bio_type, va_profile_id, response.get(self.TX_AUDIT_ID))

    def send_va_profile_email_status(self, notification_data: dict) -> None:
        """
        This method sends notification status data to VA Profile. This is part of our integration to help VA Profile
        provide better service by letting them know which emails are good, and which ones result in bounces.

        :param notification_data: the data to include with the POST request to VA Profile

        Raises:
            requests.Timeout: if the request to VA Profile times out
            RequestException: if something unexpected happens when sending the request
        """

        headers = {'Authorization': f'Bearer {self.va_profile_token}'}
        url = f'{self.va_profile_url}/contact-information-vanotify/notify/status'

        self.logger.debug(
            'Sending email status to VA Profile with url: %s | notification: %s', url, notification_data.get('id')
        )

        # make POST request to VA Profile endpoint for notification statuses
        # raise errors if they occur, they will be handled by the calling function
        try:
            response = requests.post(url, json=notification_data, headers=headers, timeout=(3.05, 1))
        except requests.Timeout:
            self.logger.warning(
                'Request timeout attempting to send email status to VA Profile for notification %s | retrying...',
                notification_data.get('id'),
            )
            raise
        except requests.RequestException as e:
            self.logger.exception(
                'Unexpected request exception, email status NOT sent to VA Profile for notification %s'
                ' | Exception: %s',
                notification_data.get('id'),
                e,
            )
            raise

        self.logger.info(
            'VA Profile response when receiving status of notification %s | status code: %s | json: %s',
            notification_data.get('id'),
            response.status_code,
            response.json(),
        )

from __future__ import annotations

from enum import Enum
from http.client import responses
from typing import TYPE_CHECKING, Dict, List

import iso8601
import requests
from app.va.identifier import OIDS, IdentifierType, transform_to_fhir_format
from app.va.va_profile import NoContactInfoException, VAProfileNonRetryableException, VAProfileRetryableException
from app.va.va_profile.exceptions import (CommunicationItemNotFoundException, CommunicationPermissionDenied,
                                          VAProfileIDNotFoundException)

if TYPE_CHECKING:
    from app.models import RecipientIdentifier

    from va_profile_types import (CommunicationPermissions, ContactInformation, Profile, Telephone)


VA_NOTIFY_TO_VA_PROFILE_NOTIFICATION_TYPES = {
    'email': 'Email',
    'sms': 'Text',
}


class NotificationType(Enum):
    EMAIL = 'Email'
    TEXT = 'Text'


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

    def get_telephone(self, va_profile_id: RecipientIdentifier) -> str:
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

    def get_email(self, va_profile_id: RecipientIdentifier) -> str:
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

    def get_telephone_with_permission(self, va_profile_id: RecipientIdentifier, communication_item_id: str) -> str:
        """
        Retrieve the telephone number from the profile information for a given VA profile ID.

        Args:
            va_profile_id (RecipientIdentifier): The VA profile ID to retrieve the telephone number for.
            communication_item_id (str): The ID of the communication item.

        Returns:
            str: The telephone number retrieved from the VA Profile service.

        Raises:
            CommunicationPermissionDenied: If communication permission is denied for the given parameters
        """
        profile = self.get_profile(va_profile_id)
        communication_allowed = self.get_is_communication_allowed_from_profile(profile, communication_item_id,
                                                                               NotificationType.TEXT.value)
        if not communication_allowed:
            raise CommunicationPermissionDenied

        contact_info: ContactInformation = profile.get('contactInformation', {})
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

    def get_email_with_permission(self, va_profile_id: RecipientIdentifier, communication_item_id: str) -> str:
        """
        Retrieve the email address from the profile information for a given VA profile ID.

        Args:
            va_profile_id (RecipientIdentifier): The VA profile ID to retrieve the email address for.
            communication_item_id (str): The ID of the communication item.

        Returns:
            str: The email address retrieved from the VA Profile service.

        Raises:
            CommunicationPermissionDenied: If communication permission is denied for the given parameters
        """
        profile = self.get_profile(va_profile_id)
        communication_allowed = self.get_is_communication_allowed_from_profile(profile, communication_item_id,
                                                                               NotificationType.EMAIL.value)
        if not communication_allowed:
            raise CommunicationPermissionDenied

        contact_info: ContactInformation = profile.get('contactInformation', {})
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

    def get_is_communication_allowed(
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

    def get_is_communication_allowed_from_profile(
        self,
        profile: Profile,
        communication_item_id: str,
        notification_type: str,
    ) -> bool:
        """
        Determine if communication is allowed for a given recipient, communication item, and notification type.

        Args:
            profile (Profile): The recipient's profile.
            communication_item_id (str): The ID of the communication item.
            notification_type (str): The type of the notification.

        Returns:
            bool: True if communication is allowed, False otherwise.

        Raises:
            CommunicationItemNotFoundException: If no communication permissions are found for the given parameters.
        """

        communication_permissions: CommunicationPermissions = profile.get(
            'communicationPermissions', {}
        )
        self.logger.debug(
            'V3 Profile -- Parsing Communication Permissions for \
              notification_type: %s -- %s',
            notification_type,
            communication_permissions,
        )
        for perm in communication_permissions:
            self.logger.debug(
                'V3 Profile -- Found communication item id %s on vaProfileId %s',
                perm['communicationItemId'],
                perm['vaProfileId'],
            )
            if (
                perm['communicationChannelName'] == notification_type
                and perm['communicationItemId'] == communication_item_id
            ):
                self.logger.debug(
                    'V3 Profile -- %s notification:  Value of allowed is %s',
                    perm['communicationChannelName'],
                    perm['allowed'],
                )
                self.statsd_client.incr('clients.va-profile.get-communication-item-permission.success')
                assert isinstance(perm['allowed'], bool)
                return perm['allowed']

        self.logger.debug(
            'V3 Profile -- did not have permission for communication item %s and channel %s',
            communication_item_id,
            notification_type,
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

        elif isinstance(error, requests.RequestException):
            self.statsd_client.incr('clients.va-profile.error.request_exception')
            failure_message = 'VA Profile returned RequestException while querying for VA Profile ID'

            if isinstance(error, requests.Timeout):
                failure_message = f'VA Profile request timed out for VA Profile ID {va_profile_id_value}.'

            exception = VAProfileRetryableException(failure_message)
            exception.failure_reason = failure_message

            raise exception from error

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
            self.logger.exception(
                'Request timeout attempting to send email status to VA Profile for notification %s | retrying...',
                notification_data.get('id'),
            )
            raise
        except requests.RequestException:
            self.logger.exception(
                'Unexpected request exception.  E-mail status NOT sent to VA Profile for notification %s.',
                notification_data.get('id'),
            )
            raise

        self.logger.info(
            'VA Profile response when receiving status of notification %s | status code: %s | json: %s',
            notification_data.get('id'),
            response.status_code,
            response.json(),
        )

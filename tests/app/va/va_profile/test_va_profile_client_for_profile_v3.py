import json
import random
from urllib import parse
from datetime import datetime, timedelta

import pytest
import requests
import requests_mock

from app.celery.contact_information_tasks import lookup_contact_info
from app.exceptions import NotificationPermanentFailureException
from app.feature_flags import FeatureFlag
from app.models import EMAIL_TYPE, SMS_TYPE, RecipientIdentifier
from app.va.identifier import IdentifierType, OIDS, transform_to_fhir_format
from app.va.va_profile.exceptions import (
    NoContactInfoException,
    InvalidPhoneNumberException,
    VAProfileIDNotFoundException,
    VAProfileNonRetryableException,
    VAProfileRetryableException,
)
from app.va.va_profile.va_profile_client import CommunicationChannel, VALID_PHONE_TYPES_FOR_SMS_DELIVERY
from app.va.va_profile.va_profile_types import Telephone

from tests.app.conftest import MOCK_VA_PROFILE_URL
from tests.app.factories.feature_flag import mock_feature_flag


def telephone_entry(
    create_date=datetime.today(), phone_type='MOBILE', classification_code='0', name_for_debugging='test mobile phone'
):
    area_code = random.randint(100, 999)
    phone_number = random.randint(100000, 9999999)
    return {
        'createDate': f'{create_date}',
        'updateDate': f'{create_date}',
        'txAuditId': '6706b496-d727-401f-8df7-d6fc9adef0e7',
        'sourceSystem': name_for_debugging,
        'sourceDate': '2022-06-09T15:11:58Z',
        'originatingSourceSystem': 'VETSGOV',
        'sourceSystemUser': '1012833438V267437',
        'effectiveStartDate': '2022-06-09T15:11:58Z',
        'vaProfileId': 1550370,
        'telephoneId': 293410,
        'internationalIndicator': False,
        'phoneType': phone_type,
        'countryCode': '1',
        'areaCode': f'{area_code}',
        'phoneNumber': f'{phone_number}',
        'classification': {'classificationCode': classification_code},
    }


@pytest.fixture(scope='function')
def mock_response():
    with open('tests/app/va/va_profile/mock_response.json', 'r') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def recipient_identifier():
    return RecipientIdentifier(notification_id='123456', id_type=IdentifierType.VA_PROFILE_ID, id_value='1234')


@pytest.fixture(scope='module')
def id_with_aaid(recipient_identifier):
    return transform_to_fhir_format(recipient_identifier)


@pytest.fixture(scope='module')
def oid(recipient_identifier):
    return OIDS.get(recipient_identifier.id_type)


@pytest.fixture(scope='module')
def url(oid, id_with_aaid):
    return f'{MOCK_VA_PROFILE_URL}/profile-service/profile/v3/{oid}/{id_with_aaid}'


class TestVAProfileClient:
    def test_get_email_calls_endpoint_and_returns_email_address(
        self,
        rmock,
        mock_va_profile_client,
        mock_response,
        recipient_identifier,
        url,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        rmock.post(url, json=mock_response, status_code=200)

        result = mock_va_profile_client.get_email_with_permission(
            recipient_identifier,
            sample_notification(gen_type=EMAIL_TYPE),
        )
        email = result.recipient

        assert email == mock_response['profile']['contactInformation']['emails'][0]['emailAddressText']
        assert rmock.called

    def test_get_email_raises_NoContactInfoException_if_no_emails_exist(
        self,
        rmock,
        mock_va_profile_client,
        mock_response,
        recipient_identifier,
        url,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        mock_response['profile']['contactInformation']['emails'] = []
        rmock.post(url, json=mock_response, status_code=200)

        with pytest.raises(NoContactInfoException):
            mock_va_profile_client.get_email_with_permission(
                recipient_identifier,
                sample_notification(gen_type=EMAIL_TYPE),
            )

    def test_get_profile_calls_correct_url(
        self,
        rmock,
        mock_va_profile_client,
        mock_response,
        recipient_identifier,
        url,
        id_with_aaid,
        oid,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        rmock.post(url, json=mock_response, status_code=200)

        mock_va_profile_client.get_email_with_permission(recipient_identifier, sample_notification())

        assert rmock.called

        escaped_id = parse.quote(id_with_aaid, safe='')
        expected_url = f'{MOCK_VA_PROFILE_URL}/profile-service/profile/v3/{oid}/{escaped_id}'

        assert rmock.request_history[0].url == expected_url

    def test_get_email_raises_exception_when_failed_request(
        self,
        rmock,
        mock_va_profile_client,
        recipient_identifier,
        url,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        response = {
            'messages': [
                {
                    'code': 'CORE103',
                    'key': '_CUF_NOT_FOUND',
                    'text': 'The ContactInformationBio for id/criteria 103 could not be found. Please correct your requ...',
                    'severity': 'INFO',
                }
            ],
            'txAuditId': 'dca32cae-b410-46c5-b61b-9a382567843f',
            'status': 'COMPLETED_FAILURE',
        }
        rmock.post(url, json=response, status_code=200)

        with pytest.raises(VAProfileNonRetryableException):
            mock_va_profile_client.get_email_with_permission(
                recipient_identifier, sample_notification(gen_type=EMAIL_TYPE)
            )

    def test_get_telephone_calls_endpoint_and_returns_phone_number(
        self,
        rmock,
        mock_va_profile_client,
        mock_response,
        recipient_identifier,
        url,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        rmock.post(url, json=mock_response, status_code=200)

        result = mock_va_profile_client.get_telephone_with_permission(recipient_identifier, sample_notification())
        telephone = result.recipient

        assert telephone is not None
        assert rmock.called

    @pytest.mark.parametrize(
        'classification_code, expected',
        [
            *[(code, True) for code in VALID_PHONE_TYPES_FOR_SMS_DELIVERY],
            (None, True),  # if no classification code exists, fall back to True
            (1, False),  # LANDLINE
            (3, False),  # INVALID
            (4, False),  # OTHER
        ],
    )
    def test_has_valid_telephone_classification(self, mock_va_profile_client, classification_code, expected):
        telephone_instance: Telephone = {
            'createDate': '2023-10-01',
            'updateDate': '2023-10-02',
            'txAuditId': 'TX123456',
            'sourceSystem': 'SystemA',
            'sourceDate': '2023-10-01',
            'originatingSourceSystem': 'SystemB',
            'sourceSystemUser': 'User123',
            'effectiveStartDate': '2023-10-01',
            'vaProfileId': 12345,
            'telephoneId': 67890,
            'internationalIndicator': False,
            'phoneType': 'Mobile',
            'countryCode': '1',
            'areaCode': '123',
            'phoneNumber': '4567890',
            'classification': {'classificationCode': classification_code, 'classificationName': 'SOME NAME'},
        }
        if classification_code is None:
            telephone_instance.pop('classification')

        mock_contact_info = {'vaProfileId': 'test', 'txAuditId': '1234'}
        if expected:
            assert mock_va_profile_client.has_valid_mobile_telephone_classification(
                telephone_instance, mock_contact_info
            )
        else:
            with pytest.raises(InvalidPhoneNumberException):
                mock_va_profile_client.has_valid_mobile_telephone_classification(telephone_instance, mock_contact_info)


class TestVAProfileClientExceptionHandling:
    def test_get_telephone_raises_NoContactInfoException_if_no_telephones_exist(
        self,
        rmock,
        mock_va_profile_client,
        mock_response,
        recipient_identifier,
        url,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        mock_response['profile']['contactInformation']['telephones'] = []
        rmock.post(url, json=mock_response, status_code=200)

        with pytest.raises(NoContactInfoException):
            mock_va_profile_client.get_telephone_with_permission(recipient_identifier, sample_notification())

    def test_get_telephone_raises_NoContactInfoException_if_no_mobile_telephones_exist(
        self, rmock, mock_va_profile_client, mock_response, recipient_identifier, url, mocker, sample_notification
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        telephones = mock_response['profile']['contactInformation']['telephones']
        mock_response['profile']['contactInformation']['telephones'] = [
            telephone for telephone in telephones if telephone['phoneType'] != 'MOBILE'
        ]
        rmock.post(url, json=mock_response, status_code=200)

        with pytest.raises(NoContactInfoException):
            mock_va_profile_client.get_telephone_with_permission(recipient_identifier, sample_notification())

    def test_get_telephone_raises_InvalidPhoneNumberException_if_number_classified_as_not_mobile(
        self, rmock, mock_va_profile_client, mock_response, recipient_identifier, url, mocker, sample_notification
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        telephones = mock_response['profile']['contactInformation']['telephones']
        for telephone in telephones:
            telephone['classification'] = {'classificationCode': 1}  # LANDLINE classification
        mock_response['profile']['contactInformation']['telephones'] = telephones
        rmock.post(url, json=mock_response, status_code=200)

        with pytest.raises(InvalidPhoneNumberException):
            mock_va_profile_client.get_telephone_with_permission(recipient_identifier, sample_notification())

    def test_get_telephone_with_permission_prefers_user_specified_mobile_phone(
        self, rmock, mock_va_profile_client, mock_response, mocker, url, recipient_identifier, sample_notification
    ):
        # A veteran has configured a mobile telephone to receive notifications.  They add an additional mobile
        # phone, and save it as their "home" phone. Even though it is technically a mobile device and is newer,
        # we should send notifications to the device specified by the user
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        today = datetime.today()
        yesterday_morning = (datetime.today() - timedelta(days=1)).replace(hour=6)
        yesterday_evening = yesterday_morning.replace(hour=20)
        home_phone_created_today = telephone_entry(today, 'HOME', 1, 'home phone created today')
        mobile_phone_created_yesterday_morning = telephone_entry(
            yesterday_morning, 'MOBILE', 0, 'mobile phone created yesterday morning'
        )
        home_phone_with_mobile_classification_created_yesterday_evening = telephone_entry(
            yesterday_evening, 'HOME', 0, 'home phone with mobile classification created yesterday evening'
        )
        contact_info = mock_response['profile']['contactInformation']
        contact_info['telephones'] = [
            home_phone_created_today,
            mobile_phone_created_yesterday_morning,
            home_phone_with_mobile_classification_created_yesterday_evening,
        ]

        rmock.post(url, json=mock_response, status_code=200)
        result = mock_va_profile_client.get_telephone_with_permission(recipient_identifier, sample_notification())
        assert (
            result.recipient
            == f"+{mobile_phone_created_yesterday_morning['countryCode']}{mobile_phone_created_yesterday_morning['areaCode']}{mobile_phone_created_yesterday_morning['phoneNumber']}"
        )

    def test_handle_exceptions_retryable_exception(self, mock_va_profile_client, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        # This test checks if VAProfileRetryableException is raised for a RequestException
        with pytest.raises(VAProfileRetryableException):
            mock_va_profile_client._handle_exceptions('some_va_profile_id', requests.RequestException())

    def test_handle_exceptions_id_not_found_exception(self, mock_va_profile_client, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        # Simulate a 404 HTTP error
        error = requests.HTTPError(response=requests.Response())
        error.response.status_code = 404
        # This test checks if VAProfileIDNotFoundException is raised for a 404 error
        with pytest.raises(VAProfileIDNotFoundException):
            mock_va_profile_client._handle_exceptions('some_va_profile_id', error)

    def test_handle_exceptions_non_retryable_exception(self, mock_va_profile_client, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        # Simulate a 400 HTTP error
        error = requests.HTTPError(response=requests.Response())
        error.response.status_code = 400
        # This test checks if VAProfileNonRetryableException is raised for a 400 error
        with pytest.raises(VAProfileNonRetryableException):
            mock_va_profile_client._handle_exceptions('some_va_profile_id', error)

    def test_handle_exceptions_timeout_exception(self, mock_va_profile_client, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        # This test checks if VAProfileRetryableExcception is raised for a Timeout exception
        # Timeout inherits from requests.RequestException, so all exceptions of type RequestException should
        # raise a VAProfileRetryableException
        with pytest.raises(VAProfileRetryableException):
            mock_va_profile_client._handle_exceptions('some_va_profile_id', requests.Timeout())

    @pytest.mark.parametrize('status', [429, 500])
    def test_client_raises_retryable_exception(
        self,
        rmock,
        mock_va_profile_client,
        recipient_identifier,
        status,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        rmock.post(requests_mock.ANY, status_code=status)

        with pytest.raises(VAProfileRetryableException):
            mock_va_profile_client.get_email_with_permission(
                recipient_identifier, sample_notification(gen_type=EMAIL_TYPE)
            )

        with pytest.raises(VAProfileRetryableException):
            mock_va_profile_client.get_email_with_permission(recipient_identifier, sample_notification())

    def test_client_raises_retryable_exception_when_request_exception_is_thrown(
        self,
        mock_va_profile_client,
        recipient_identifier,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        with requests_mock.Mocker(real_http=True) as rmock:
            rmock.post(requests_mock.ANY, exc=requests.RequestException)

            with pytest.raises(VAProfileRetryableException):
                mock_va_profile_client.get_email_with_permission(
                    recipient_identifier, sample_notification(gen_type=EMAIL_TYPE)
                )

            with pytest.raises(VAProfileRetryableException):
                mock_va_profile_client.get_email_with_permission(recipient_identifier, sample_notification())


class TestCommunicationPermissions:
    @pytest.mark.parametrize('expected', [True, False])
    def test_get_is_communication_allowed_returns_whether_permissions_granted_for_sms_communication(
        self,
        rmock,
        mock_va_profile_client,
        mock_response,
        url,
        expected,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        notification = sample_notification()
        mock_response['profile']['communicationPermissions'][0]['allowed'] = expected
        mock_response['profile']['communicationPermissions'][0]['communicationItemId'] = notification.va_profile_item_id

        allowed = mock_va_profile_client.get_is_communication_allowed_from_profile(
            mock_response['profile'], notification, CommunicationChannel.TEXT
        )

        assert allowed is expected

    @pytest.mark.parametrize('expected', [True, False])
    def test_get_is_communication_allowed_returns_whether_permissions_granted_for_email_communication(
        self,
        rmock,
        mock_va_profile_client,
        mock_response,
        url,
        expected,
        mocker,
        sample_notification,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        notification = sample_notification(gen_type=EMAIL_TYPE)
        mock_response['profile']['communicationPermissions'][1]['allowed'] = expected
        mock_response['profile']['communicationPermissions'][1]['communicationItemId'] = notification.va_profile_item_id

        allowed = mock_va_profile_client.get_is_communication_allowed_from_profile(
            mock_response['profile'], notification, CommunicationChannel.EMAIL
        )

        assert allowed is expected

    @pytest.mark.parametrize(
        'default_send, user_set, expected',
        [
            # If the user has set a preference, we always go with that and override default_send
            [True, True, True],
            [True, False, False],
            [False, True, True],
            [False, False, False],
            # If the user has not set a preference, go with the default_send
            [True, None, True],
            [False, None, False],
        ],
    )
    @pytest.mark.parametrize('notification_type', [CommunicationChannel.EMAIL, CommunicationChannel.TEXT])
    def test_get_email_or_sms_with_permission_utilizes_default_send(
        self,
        mock_va_profile_client,
        mock_response,
        recipient_identifier,
        sample_communication_item,
        sample_notification,
        sample_template,
        default_send,
        user_set,
        expected,
        notification_type,
        mocker,
    ):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        profile = mock_response['profile']
        communication_item = sample_communication_item(default_send)
        template = sample_template(communication_item_id=communication_item.id)

        notification = sample_notification(
            template=template, gen_type=EMAIL_TYPE if notification_type == CommunicationChannel.EMAIL else SMS_TYPE
        )

        if user_set is not None:
            profile['communicationPermissions'][0]['allowed'] = user_set
            profile['communicationPermissions'][0]['communicationItemId'] = notification.va_profile_item_id
            profile['communicationPermissions'][0]['communicationChannelId'] = notification_type.id
        else:
            profile['communicationPermissions'] = []

        mocker.patch.object(mock_va_profile_client, 'get_profile', return_value=profile)

        if notification_type == CommunicationChannel.EMAIL:
            client_fn = mock_va_profile_client.get_email_with_permission
        else:
            client_fn = mock_va_profile_client.get_telephone_with_permission

        result = client_fn(recipient_identifier, notification)
        assert result.communication_allowed == expected


class TestSendEmailStatus:
    mock_response = {}
    mock_notification_data = {
        'id': '2e9e6920-4f6f-4cd5-9e16-fc306fe23867',  # this is the notification id
        'reference': None,
        'to': 'test@email.com',  # this is the recipient's contact info (email)
        'status': 'delivered',  # this will specify the delivery status of the notification
        'status_reason': '',  # populated if there's additional context on the delivery status
        'created_at': '2024-07-25T10:00:00.0',
        'completed_at': '2024-07-25T11:00:00.0',
        'sent_at': '2024-07-25T11:00:00.0',
        'notification_type': EMAIL_TYPE,  # this is the channel/type of notification (email)
        'provider': 'ses',  # email provider
    }

    def test_send_va_profile_email_status_sent_successfully(self, rmock, mock_va_profile_client, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        rmock.post(requests_mock.ANY, json=self.mock_response, status_code=200)

        mock_va_profile_client.send_va_profile_email_status(self.mock_notification_data)

        assert rmock.called

        expected_url = f'{MOCK_VA_PROFILE_URL}/contact-information-vanotify/notify/status'
        assert rmock.request_history[0].url == expected_url

    def test_send_va_profile_email_status_timeout(self, rmock, mock_va_profile_client, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        rmock.post(requests_mock.ANY, exc=requests.ReadTimeout)

        with pytest.raises(requests.Timeout):
            mock_va_profile_client.send_va_profile_email_status(self.mock_notification_data)

        assert rmock.called

        expected_url = f'{MOCK_VA_PROFILE_URL}/contact-information-vanotify/notify/status'
        assert rmock.request_history[0].url == expected_url

    def test_send_va_profile_email_status_throws_exception(self, rmock, mock_va_profile_client, mocker):
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
        mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

        rmock.post(requests_mock.ANY, exc=requests.RequestException)

        with pytest.raises(requests.RequestException):
            mock_va_profile_client.send_va_profile_email_status(self.mock_notification_data)

        assert rmock.called

        expected_url = f'{MOCK_VA_PROFILE_URL}/contact-information-vanotify/notify/status'
        assert rmock.request_history[0].url == expected_url


@pytest.mark.parametrize(
    'default_send, user_set, expected',
    [
        # If the user has set a preference, we always go with that and override default_send
        [True, True, True],
        [True, False, False],
        [False, True, True],
        [False, False, False],
        # If the user has not set a preference, go with the default_send
        [True, None, True],
        [False, None, False],
    ],
)
@pytest.mark.parametrize('notification_type', [CommunicationChannel.EMAIL, CommunicationChannel.TEXT])
def test_get_email_or_sms_with_permission_utilizes_default_send(
    mock_va_profile_response,
    sample_communication_item,
    sample_notification,
    sample_template,
    default_send,
    user_set,
    expected,
    notification_type,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')
    # Test each combo, ensuring contact info responds with expected result
    channel = EMAIL_TYPE if notification_type == CommunicationChannel.EMAIL else SMS_TYPE
    profile = mock_va_profile_response['profile']
    communication_item = sample_communication_item(default_send)
    template = sample_template(template_type=channel, communication_item_id=communication_item.id)
    notification = sample_notification(
        template=template,
        gen_type=channel,
        recipient_identifiers=[{'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': '1234'}],
    )

    profile['communicationPermissions'][0]['allowed'] = user_set
    profile['communicationPermissions'][0]['communicationItemId'] = notification.va_profile_item_id
    profile['communicationPermissions'][0]['communicationChannelId'] = notification_type.id

    mocker.patch('app.va.va_profile.va_profile_client.VAProfileClient.get_profile', return_value=profile)

    if default_send:
        if user_set or user_set is None:
            # Implicit + user has not opted out
            assert lookup_contact_info(notification.id) is None
        else:
            # Implicit + user has opted out
            with pytest.raises(NotificationPermanentFailureException):
                lookup_contact_info(notification.id)
    else:
        if user_set:
            # Explicit + User has opted in
            assert lookup_contact_info(notification.id) is None
        else:
            # Explicit + User has not defined opted in
            with pytest.raises(NotificationPermanentFailureException):
                lookup_contact_info(notification.id)

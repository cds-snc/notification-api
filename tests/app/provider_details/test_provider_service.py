import pytest

from app.exceptions import InvalidProviderException
from app.models import Notification, ProviderDetails, Template, Service
from app.notifications.notification_type import NotificationType
from app.provider_details.provider_service import ProviderService


class TestGetProvider:
    def test_returns_template_provider(self, notify_api, mocker):
        provider_service = ProviderService()
        template_with_provider = mocker.Mock(Template, provider_id='some-id')

        mock_notification = mocker.Mock(Notification, template=template_with_provider)

        mock_provider = mocker.Mock(ProviderDetails)
        mock_get_provider_details = mocker.patch(
            'app.provider_details.provider_service.get_provider_details_by_id', return_value=mock_provider
        )

        assert mock_provider == provider_service.get_provider(mock_notification)

        mock_get_provider_details.assert_called_with('some-id')

    def test_raises_exception_if_template_provider_is_inactive(self, notify_api, mocker):
        provider_service = ProviderService()
        template_with_provider = mocker.Mock(Template, provider_id='some-id')

        mock_notification = mocker.Mock(Notification, template=template_with_provider)

        mock_provider = mocker.Mock(ProviderDetails, active=False)
        mock_get_provider_details = mocker.patch(
            'app.provider_details.provider_service.get_provider_details_by_id', return_value=mock_provider
        )

        with pytest.raises(InvalidProviderException):
            provider_service.get_provider(mock_notification)

        mock_get_provider_details.assert_called_with('some-id')

    def test_raises_exception_if_template_provider_cannot_be_found(self, notify_api, mocker):
        provider_service = ProviderService()
        template_with_provider = mocker.Mock(Template, provider_id='some-id')

        mock_notification = mocker.Mock(Notification, template=template_with_provider)

        mock_get_provider_details = mocker.patch(
            'app.provider_details.provider_service.get_provider_details_by_id', return_value=None
        )

        with pytest.raises(InvalidProviderException):
            provider_service.get_provider(mock_notification)

        mock_get_provider_details.assert_called_with('some-id')

    @pytest.mark.parametrize(
        'notification_type, expected_provider_id',
        [(NotificationType.EMAIL.value, 'email-provider-id'), (NotificationType.SMS.value, 'sms-provider-id')],
    )
    def test_returns_service_provider_for_notification_type_if_no_template_provider(
        self, notify_api, mocker, notification_type, expected_provider_id
    ):
        provider_service = ProviderService()
        template_without_provider = mocker.Mock(Template, provider_id=None)

        service_with_providers = mocker.Mock(
            Service, email_provider_id='email-provider-id', sms_provider_id='sms-provider-id'
        )

        mock_notification = mocker.Mock(
            Notification,
            notification_type=notification_type,
            template=template_without_provider,
            service=service_with_providers,
        )

        mock_provider = mocker.Mock(ProviderDetails)
        mock_get_provider_details = mocker.patch(
            'app.provider_details.provider_service.get_provider_details_by_id', return_value=mock_provider
        )

        assert mock_provider == provider_service.get_provider(mock_notification)

        mock_get_provider_details.assert_called_with(expected_provider_id)

    @pytest.mark.parametrize(
        'notification_type, template_provider_id, service_provider_id, expected_id',
        [
            (NotificationType.SMS.value, 't_id', 's_id', 't_id'),
            (NotificationType.SMS.value, 't_id', None, 't_id'),
            (NotificationType.SMS.value, None, 's_id', 's_id'),
            (NotificationType.SMS.value, None, None, None),
            (NotificationType.EMAIL.value, 't_id', 's_id', 't_id'),
            (NotificationType.EMAIL.value, 't_id', None, 't_id'),
            (NotificationType.EMAIL.value, None, 's_id', 's_id'),
            (NotificationType.EMAIL.value, None, None, None),
        ],
    )
    def test_get_template_or_service_provider_id(
        self, notify_api, mocker, notification_type, template_provider_id, service_provider_id, expected_id
    ):
        """
        Test the static method ProviderService._get_template_or_service_provider_id.
        """

        template_mock = mocker.Mock(Template, provider_id=template_provider_id)

        service_mock = mocker.Mock(Service, email_provider_id=service_provider_id, sms_provider_id=service_provider_id)

        notification = mocker.Mock(notification_type=notification_type, template=template_mock, service=service_mock)

        assert ProviderService._get_template_or_service_provider_id(notification) == expected_id

    def test_no_strategy_for_notification_type_when_no_template_or_service_providers_sms(self, notify_api, mocker):
        """
        For SMS messages, there is no fallback method if neither the notification's template
        nor the notification's service has an associated provider_id.
        """

        provider_service = ProviderService()
        template_without_provider = mocker.Mock(Template, provider_id=None)
        service_without_providers = mocker.Mock(Service, email_provider_id=None, sms_provider_id=None)

        notification = mocker.Mock(
            notification_type=NotificationType.SMS,
            template=template_without_provider,
            service=service_without_providers,
        )

        with pytest.raises(InvalidProviderException):
            provider_service.get_provider(notification)

    @pytest.mark.parametrize('notification_type', [NotificationType.EMAIL, NotificationType.SMS])
    def test_raises_exception_when_strategy_cannot_find_suitable_provider(
        self,
        notify_api,
        mocker,
        notification_type,
    ):
        provider_service = ProviderService()
        template_without_provider = mocker.Mock(Template, provider_id=None)
        service_without_providers = mocker.Mock(Service, email_provider_id=None, sms_provider_id=None)

        notification = mocker.Mock(
            notification_type=notification_type, template=template_without_provider, service=service_without_providers
        )

        with pytest.raises(InvalidProviderException):
            provider_service.get_provider(notification)

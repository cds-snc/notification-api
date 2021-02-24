import pytest

from app.models import Notification, ProviderDetails, Template, Service
from app.notifications.notification_type import NotificationType
from app.provider_details.provider_selection_strategy_interface import ProviderSelectionStrategyInterface
from app.provider_details.provider_service import ProviderService


class ExampleStrategyOne(ProviderSelectionStrategyInterface):

    @staticmethod
    def get_label() -> str:
        return 'EXAMPLE_STRATEGY_ONE'

    @staticmethod
    def validate(notification_type: NotificationType):
        pass

    @staticmethod
    def get_provider(notification: Notification) -> ProviderDetails:
        pass


class ExampleStrategyTwo(ProviderSelectionStrategyInterface):

    @staticmethod
    def get_label() -> str:
        return 'EXAMPLE_STRATEGY_TWO'

    @staticmethod
    def validate(notification_type: NotificationType):
        pass

    @staticmethod
    def get_provider(notification: Notification) -> ProviderDetails:
        pass


@pytest.fixture
def provider_service():
    provider_service = ProviderService()
    provider_service.init_app(
        email_provider_selection_strategy_label='EXAMPLE_STRATEGY_ONE',
        sms_provider_selection_strategy_label='EXAMPLE_STRATEGY_TWO'
    )

    assert provider_service.strategies[NotificationType.EMAIL] == ExampleStrategyOne
    assert provider_service.strategies[NotificationType.SMS] == ExampleStrategyTwo

    return provider_service


class TestInitApp:

    def test_fails_to_initialise_with_unknown_email_strategy(self):
        provider_service = ProviderService()

        with pytest.raises(Exception):
            provider_service.init_app(
                email_provider_selection_strategy_label='UNKNOWN_EMAIL_STRATEGY',
                sms_provider_selection_strategy_label='EXAMPLE_STRATEGY_TWO'
            )

    def test_fails_to_initialise_with_unknown_sms_strategy(self):
        provider_service = ProviderService()

        with pytest.raises(Exception):
            provider_service.init_app(
                email_provider_selection_strategy_label='EXAMPLE_STRATEGY_ONE',
                sms_provider_selection_strategy_label='UNKNOWN_SMS_STRATEGY'
            )


class TestValidateStrategies:

    def test_passes_if_all_strategies_valid(self, mocker, provider_service):
        for _, strategy in provider_service.strategies.items():
            mocker.patch.object(strategy, 'validate', side_effect=None)

        provider_service.validate_strategies()

        for notification_type, strategy in provider_service.strategies.items():
            strategy.validate.assert_called_with(notification_type)

    def test_fails_if_email_strategy_is_not_valid(self, mocker, provider_service):
        email_strategy = provider_service.strategies[NotificationType.EMAIL]
        mocker.patch.object(email_strategy, 'validate', side_effect=Exception)

        with pytest.raises(Exception):
            provider_service.validate_strategies()

    def test_fails_if_sms_strategy_is_not_valid(self, mocker, provider_service):
        sms_strategy = provider_service.strategies[NotificationType.SMS]
        mocker.patch.object(sms_strategy, 'validate', side_effect=Exception)

        with pytest.raises(Exception):
            provider_service.validate_strategies()


class TestGetProvider:
    def test_returns_template_provider(self, mocker, provider_service):

        template_with_provider = mocker.Mock(Template, provider_id='some-id')

        mock_notification = mocker.Mock(Notification, template=template_with_provider)

        mock_provider = mocker.Mock(ProviderDetails)
        mock_get_provider_details = mocker.patch(
            'app.provider_details.provider_service.get_provider_details_by_id',
            return_value=mock_provider
        )

        assert mock_provider == provider_service.get_provider(mock_notification)

        mock_get_provider_details.assert_called_with('some-id')

    @pytest.mark.parametrize(
        'notification_type, expected_provider_id', [
            (NotificationType.EMAIL, 'email-provider-id'),
            (NotificationType.SMS, 'sms-provider-id')
        ]
    )
    def test_returns_service_provider_for_notification_type_if_no_template_provider(
            self,
            mocker,
            provider_service,
            notification_type,
            expected_provider_id
    ):
        template_without_provider = mocker.Mock(Template, provider_id=None)

        service_with_providers = mocker.Mock(
            Service,
            email_provider_id='email-provider-id',
            sms_provider_id='sms-provider-id'
        )

        mock_notification = mocker.Mock(
            Notification,
            notification_type=notification_type,
            template=template_without_provider,
            service=service_with_providers
        )

        mock_provider = mocker.Mock(ProviderDetails)
        mock_get_provider_details = mocker.patch(
            'app.provider_details.provider_service.get_provider_details_by_id',
            return_value=mock_provider
        )

        assert mock_provider == provider_service.get_provider(mock_notification)

        mock_get_provider_details.assert_called_with(expected_provider_id)

    @pytest.mark.parametrize(
        'notification_type, expected_strategy', [
            (NotificationType.EMAIL, ExampleStrategyOne),
            (NotificationType.SMS, ExampleStrategyTwo)
        ]
    )
    def test_uses_strategy_for_notification_type_when_no_template_or_service_providers(
            self,
            mocker,
            provider_service,
            notification_type,
            expected_strategy
    ):
        template_without_provider = mocker.Mock(Template, provider_id=None)
        service_without_providers = mocker.Mock(Service, email_provider_id=None, sms_provider_id=None)

        provider = mocker.Mock()
        mocker.patch.object(expected_strategy, 'get_provider', return_value=provider)

        notification = mocker.Mock(
            notification_type=notification_type,
            template=template_without_provider,
            service=service_without_providers
        )

        assert provider_service.get_provider(notification) == provider
        expected_strategy.get_provider.assert_called_with(notification)

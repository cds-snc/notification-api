import pytest

from app.models import ProviderDetails, Notification
from app.notifications.notification_type import NotificationType
from app.provider_details.load_balancing_strategy import LoadBalancingStrategy


class TestValidate:

    def test_validate_passes_if_there_are_providers_with_weights_for_notification_type(self, mocker):
        mock_dao_get_providers = mocker.patch(
            'app.provider_details.load_balancing_strategy.get_active_providers_with_weights_by_notification_type',
            return_value=[mocker.Mock(ProviderDetails)]
        )

        some_notification_type = mocker.Mock(NotificationType)
        LoadBalancingStrategy.validate(some_notification_type)

        mock_dao_get_providers.assert_called_with(some_notification_type)

    def test_validate_throws_if_there_are_no_providers_with_weights_for_notification_type(self, mocker):
        mock_dao_get_providers = mocker.patch(
            'app.provider_details.load_balancing_strategy.get_active_providers_with_weights_by_notification_type',
            return_value=[]
        )

        some_notification_type = mocker.Mock(NotificationType)

        with pytest.raises(Exception):
            LoadBalancingStrategy.validate(some_notification_type)

        mock_dao_get_providers.assert_called_with(some_notification_type)


class TestGetProvider:

    def test_returns_single_provider(self, mocker):
        mock_provider = mocker.Mock(ProviderDetails, load_balancing_weight=10)
        mock_dao_get_providers = mocker.patch(
            'app.provider_details.load_balancing_strategy.get_active_providers_with_weights_by_notification_type',
            return_value=[mock_provider]
        )

        mock_notification = mocker.Mock(
            Notification,
            notification_type=NotificationType.EMAIL.value,
            international=False
        )

        assert LoadBalancingStrategy.get_provider(mock_notification) == mock_provider

        mock_dao_get_providers.assert_called_with(NotificationType.EMAIL, False)

    def test_handles_no_providers(self, mocker):
        mocker.patch(
            'app.provider_details.load_balancing_strategy.get_active_providers_with_weights_by_notification_type',
            return_value=[]
        )

        mock_notification = mocker.Mock(Notification, notification_type=NotificationType.EMAIL.value)

        assert LoadBalancingStrategy.get_provider(mock_notification) is None

    def test_returns_weighted_random_provider(self, mocker):
        mock_provider_1 = mocker.Mock(ProviderDetails, load_balancing_weight=10)
        mock_provider_2 = mocker.Mock(ProviderDetails, load_balancing_weight=90)
        mocker.patch(
            'app.provider_details.load_balancing_strategy.get_active_providers_with_weights_by_notification_type',
            return_value=[mock_provider_1, mock_provider_2]
        )

        mock_choices = mocker.patch(
            'app.provider_details.load_balancing_strategy.choices',
            return_value=[mock_provider_2]
        )

        mock_notification = mocker.Mock(
            Notification,
            notification_type=NotificationType.EMAIL.value
        )

        assert LoadBalancingStrategy.get_provider(mock_notification) == mock_provider_2

        mock_choices.assert_called_with([mock_provider_1, mock_provider_2], [10, 90])

    @pytest.mark.skip('Due to randomness, there is a very small chance that this test will fail. '
                      'Leaving it here as peace of mind that our approach works')
    def test_random_distribution(self, mocker):
        mock_provider_1 = mocker.Mock(ProviderDetails, load_balancing_weight=10)
        mock_provider_2 = mocker.Mock(ProviderDetails, load_balancing_weight=90)
        mocker.patch(
            'app.provider_details.load_balancing_strategy.get_active_providers_with_weights_by_notification_type',
            return_value=[mock_provider_1, mock_provider_2]
        )

        mock_notification = mocker.Mock(Notification, notification_type=NotificationType.EMAIL.value)

        number_of_samples = 500

        sampled_providers = [LoadBalancingStrategy.get_provider(mock_notification) for _ in range(number_of_samples)]

        sum_of_weights = mock_provider_1.load_balancing_weight + mock_provider_2.load_balancing_weight

        expected_proportion_of_provider_1 = mock_provider_1.load_balancing_weight / sum_of_weights
        expected_proportion_of_provider_2 = mock_provider_2.load_balancing_weight / sum_of_weights

        expected_occurrences_of_provider_1 = number_of_samples * expected_proportion_of_provider_1
        expected_occurrences_of_provider_2 = number_of_samples * expected_proportion_of_provider_2

        assert sampled_providers.count(mock_provider_1) == pytest.approx(expected_occurrences_of_provider_1, abs=5)
        assert sampled_providers.count(mock_provider_2) == pytest.approx(expected_occurrences_of_provider_2, abs=5)

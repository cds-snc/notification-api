import pytest

from app.models import ProviderDetails, Notification
from app.notifications.notification_type import NotificationType
from app.provider_details.highest_priority_strategy import HighestPriorityStrategy


class TestValidate:
    def test_validate_passes_if_there_is_a_highest_priority_active_provider(self, mocker):
        mock_dao_get_provider = mocker.patch(
            'app.provider_details.highest_priority_strategy.get_highest_priority_active_provider_by_notification_type',
            return_value=mocker.Mock(ProviderDetails)
        )

        some_notification_type = mocker.Mock(NotificationType)
        HighestPriorityStrategy.validate(some_notification_type)

        mock_dao_get_provider.assert_called_with(some_notification_type)

    def test_validate_throws_if_there_is_no_highest_priority_active_provider(self, mocker):
        mock_dao_get_provider = mocker.patch(
            'app.provider_details.highest_priority_strategy.get_highest_priority_active_provider_by_notification_type',
            return_value=None
        )

        some_notification_type = mocker.Mock(NotificationType)

        with pytest.raises(Exception):
            HighestPriorityStrategy.validate(some_notification_type)

        mock_dao_get_provider.assert_called_with(some_notification_type)


class TestGetProvider:
    def test_get_provider_returns_highest_priority_provider(self, mocker):
        mock_provider = mocker.Mock(ProviderDetails)
        mock_dao_get_provider = mocker.patch(
            'app.provider_details.highest_priority_strategy.get_highest_priority_active_provider_by_notification_type',
            return_value=mock_provider
        )

        mock_notification = mocker.Mock(
            Notification,
            notification_type=NotificationType.EMAIL.value,
            international=False
        )

        assert HighestPriorityStrategy.get_provider(mock_notification) == mock_provider

        mock_dao_get_provider.assert_called_with(NotificationType.EMAIL, False)

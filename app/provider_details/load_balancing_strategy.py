from random import choices
from typing import Optional

from .provider_selection_strategy_interface import ProviderSelectionStrategyInterface
from app.notifications.notification_type import NotificationType
from app.dao.provider_details_dao import get_active_providers_with_weights_by_notification_type
from app.models import Notification, ProviderDetails


class LoadBalancingStrategy(ProviderSelectionStrategyInterface):
    """
    Provider selection strategy that returns random provider based on
    configured weights stored in provider_details table
    """

    @staticmethod
    def get_label() -> str:
        return 'LOAD_BALANCING'

    @staticmethod
    def validate(notification_type: NotificationType):
        if not get_active_providers_with_weights_by_notification_type(notification_type):
            raise Exception(
                f"Load Balancing Strategy cannot be used for {notification_type} notifications "
                "because there are no matching active providers that have load balancing weights"
            )

    @staticmethod
    def get_provider(notification: Notification) -> Optional[ProviderDetails]:
        providers = get_active_providers_with_weights_by_notification_type(
            NotificationType(notification.notification_type),
            notification.international
        )

        if providers:
            [randomly_chosen_provider] = choices(providers, [provider.load_balancing_weight for provider in providers])
            return randomly_chosen_provider

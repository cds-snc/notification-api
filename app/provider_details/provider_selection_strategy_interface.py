from typing import Type, Dict

from app.models import ProviderDetails, Notification
from app.notifications.notification_type import NotificationType

STRATEGY_REGISTRY: Dict[str, Type['ProviderSelectionStrategyInterface']] = {}


class ProviderSelectionStrategyInterface:
    """
    Abstract class as interface for provider selection strategies.

    Strategies that inherit from this interface, once imported, will be added to STRATEGY_REGISTRY
    We import strategies in the provider_details module __init__.py to achieve this.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        STRATEGY_REGISTRY[cls.get_label()] = cls

    @staticmethod
    def get_label() -> str:
        raise NotImplementedError()

    @staticmethod
    def validate(notification_type: NotificationType) -> None:
        raise NotImplementedError()

    @staticmethod
    def get_provider(notification: Notification) -> ProviderDetails:
        raise NotImplementedError()

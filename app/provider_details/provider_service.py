from typing import Type, Dict, Optional

from app.dao.provider_details_dao import get_provider_details_by_id
from app.models import Notification, ProviderDetails
from app.notifications.notification_type import NotificationType
from app.provider_details.provider_selection_strategy_interface import ProviderSelectionStrategyInterface, \
    STRATEGY_REGISTRY


class ProviderService:

    def __init__(self):
        self._strategies: Dict[NotificationType, Optional[Type[ProviderSelectionStrategyInterface]]] = {
            NotificationType.EMAIL: None,
            NotificationType.SMS: None
        }

    def init_app(
            self,
            email_provider_selection_strategy_label: str,
            sms_provider_selection_strategy_label: str
    ) -> None:
        try:
            email_strategy = STRATEGY_REGISTRY[email_provider_selection_strategy_label]
            sms_strategy = STRATEGY_REGISTRY[sms_provider_selection_strategy_label]
        except KeyError as e:
            [failed_key] = e.args
            raise Exception(
                f"Could not initialise ProviderService with strategy '{failed_key}' "
                "- has the strategy been declared as a subclass of ProviderSelectionStrategyInterface?"
            )
        else:
            self._strategies[NotificationType.EMAIL] = email_strategy
            self._strategies[NotificationType.SMS] = sms_strategy

    @property
    def strategies(self):
        return self._strategies

    def validate_strategies(self) -> None:
        for notification_type, strategy in self.strategies.items():
            strategy.validate(notification_type)

    def get_provider(self, notification: Notification) -> ProviderDetails:
        template_or_service_provider_id = self._get_template_or_service_provider_id(notification)
        if template_or_service_provider_id:
            return get_provider_details_by_id(template_or_service_provider_id)

        provider_selection_strategy = self._strategies[NotificationType(notification.notification_type)]
        return provider_selection_strategy.get_provider(notification)

    @staticmethod
    def _get_template_or_service_provider_id(notification: Notification) -> Optional[str]:
        if notification.template.provider_id:
            return notification.template.provider_id

        service_provider_id = {
            NotificationType.EMAIL: notification.service.email_provider_id,
            NotificationType.SMS: notification.service.sms_provider_id
        }[NotificationType(notification.notification_type)]

        if service_provider_id:
            return service_provider_id

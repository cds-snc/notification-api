from flask import current_app

from app.dao.provider_details_dao import get_provider_details_by_id
from app.exceptions import InvalidProviderException
from app.models import Notification, ProviderDetails
from app.notifications.notification_type import NotificationType


class ProviderService:
    def __init__(self):
        self._strategies: dict[NotificationType, None] = {
            NotificationType.EMAIL: None,
            NotificationType.SMS: None,
        }

    @property
    def strategies(self):
        """This is a dictionary with notification types as the keys."""
        return self._strategies

    def get_provider(
        self,
        notification: Notification,
    ) -> ProviderDetails:
        """
        Return an instance of ProviderDetails that is appropriate for the given notification.
        """

        # This is a UUID (ProviderDetails primary key).
        provider_id = self._get_template_or_service_provider_id(notification)
        if provider_id is None:
            raise InvalidProviderException('Could not determine a provider ID.')

        current_app.logger.debug(
            'Provider service getting provider for notification = %s, provider_id = %s', notification.id, provider_id
        )

        provider = get_provider_details_by_id(provider_id)

        if provider is None:
            raise InvalidProviderException(f'The provider {provider_id} could not be found.')
        elif not provider.active:
            raise InvalidProviderException(f'The provider {provider.display_name} is not active.')

        current_app.logger.debug(
            'Returning provider: %s, for notification %s',
            None if provider is None else provider.display_name,
            notification.id,
        )

        return provider

    @staticmethod
    def _get_template_or_service_provider_id(notification: Notification) -> str | None:
        """
        Return a primary key (UUID) for an instance of ProviderDetails using this criteria:
            1. Use the notification template's provider_id first.
            2. Use the notification service's provider_id if the template's provider_id is null.

        Return None if neither criterion yields a provider ID.
        """

        # The template provider_id is nullable foreign key (UUID).
        # TODO #957 - The field is nullable, but what does SQLAlchemy return?  An empty string?
        # Testing for None broke a user flows test; user flows is since removed but this is possibly an issue?
        if notification.template.provider_id is not None:
            current_app.logger.debug(
                'Found template provider ID %s, for notification %s', notification.template.provider_id, notification.id
            )
            return notification.template.provider_id

        # A template provider_id is not available.  Try using a service provider_id, which might also be None.
        if notification.notification_type == NotificationType.EMAIL.value:
            current_app.logger.debug(
                'Service provider e-mail ID %s, for notification %s',
                notification.service.email_provider_id,
                notification.id,
            )
            return notification.service.email_provider_id
        elif notification.notification_type == NotificationType.SMS.value:
            current_app.logger.debug(
                'Service provider SMS ID %s, for notification %s', notification.service.sms_provider_id, notification.id
            )
            return notification.service.sms_provider_id

        # TODO #957 - What about letters?  That is the 3rd enumerated value in NotificationType
        # and Notification.notification_type.
        current_app.logger.critical(
            'Unanticipated notification type: %s for notification %s', notification.notification_type, notification.id
        )
        return None

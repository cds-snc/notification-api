from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery, va_profile_client
from app.dao.communication_item_dao import get_communication_item
from app.dao.notifications_dao import update_notification_status_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.feature_flags import FeatureFlag, is_feature_enabled
from app.models import RecipientIdentifier, Notification, NOTIFICATION_PREFERENCES_DECLINED
from app.notifications.process_notifications import send_to_queue_for_recipient_info_based_on_recipient_identifier
from app.va.va_profile.va_profile_client import CommunicationItemNotFoundException


@notify_celery.task(bind=True, name="process-communication-item-request", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_communication_item_request(
        self, id_type: str, id_value: str, template_id: str, notification: Notification
) -> bool:
    if user_has_given_permission(id_type, id_value, template_id):
        send_to_queue_for_recipient_info_based_on_recipient_identifier(
            notification=notification,
            id_type=id_type
        )
    else:
        update_notification_status_by_id(notification.id, NOTIFICATION_PREFERENCES_DECLINED)


def user_has_given_permission(id_type: str, id_value: str, template_id: str):
    if not is_feature_enabled(FeatureFlag.CHECK_USER_COMMUNICATION_PERMISSIONS_ENABLED):
        current_app.logger.info(f'Communication item permissions feature flag is off')
        return True

    identifier = RecipientIdentifier(id_type=id_type, id_value=id_value)
    template = dao_get_template_by_id(template_id)

    communication_item_id = template.communication_item_id

    if not communication_item_id:
        current_app.logger.info(f'User {id_value} does not have requested communication item id')
        return True

    communication_item = get_communication_item(communication_item_id)

    try:
        is_allowed = va_profile_client.get_is_communication_allowed(identifier, communication_item.va_profile_item_id)
        current_app.logger.info(f'Value of permission for item {communication_item.va_profile_item_id} for user '
                                f'{id_value}: {is_allowed}')
        return is_allowed
    except CommunicationItemNotFoundException:
        return True

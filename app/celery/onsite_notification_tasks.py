from flask import current_app
from app import notify_celery
from app import va_onsite_client


@notify_celery.task(name="send-va-onsite-notification-task")
def send_va_onsite_notification_task(va_profile_id: str, template_id: str, onsite_enabled: bool = False):
    """ This function is used by celery to POST a notification to VA_Onsite. """
    current_app.logger.info(f'Calling va_onsite_notification_task with va_profile_id: {va_profile_id} | ' +
                            f'Template onsite_notification set to: {onsite_enabled}')

    if onsite_enabled and va_profile_id:
        data = {'onsite_notification': {"template_id": template_id, "va_profile_id": va_profile_id}}
        va_onsite_client.post_onsite_notification(data)

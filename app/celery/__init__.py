from typing import Any, Dict, Optional

from flask import current_app

from app import config, models

# Default retry periods for sending notifications.
RETRY_DEFAULT = 300
RETRY_HIGH = 25


class CeleryParams(object):
    # Important to load from the object and not the module to avoid
    # circular imports, back and forth between the app and celery modules.

    RETRY_PERIODS = {
        models.BULK: RETRY_DEFAULT,
        models.NORMAL: RETRY_DEFAULT,
        models.PRIORITY: RETRY_HIGH,
    }

    @staticmethod
    def retry(notification_process_type: str, countdown: Optional[int] = None) -> Dict[str, Any]:
        """
        Build task params for the sending parameter retry tasks.

        If the notification is a high priority SMS, set the retry policy to retry every 25 seconds
        else fall back to the default retry policy of retrying every 5 minutes.

        Provide an override parameter for cases the calling task wants to override the retry policy.
        """
        params: dict[str, Any] = {"queue": config.RETRY}
        if current_app.config["FF_CELERY_CUSTOM_TASK_PARAMS"] is False:
            return params

        if countdown is not None:
            params["countdown"] = countdown
        else:
            # Overring the retry policy is only supported for SMS for now;
            # email support coming later.
            params["countdown"] = CeleryParams.RETRY_PERIODS[notification_process_type]

        return params

from datetime import datetime, timezone

from flask import current_app, json
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import annual_limit_client, bounce_rate_client, notify_celery, statsd_client
from app.config import QueueNames
from app.dao import notifications_dao
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_service_for_day,
)
from app.models import NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE
from app.notifications.callbacks import _check_and_queue_callback_task
from app.notifications.notifications_ses_callback import (
    _check_and_queue_complaint_callback_task,
    get_aws_responses,
    handle_complaint,
)
from app.utils import prepare_notification_counts_for_seeding
from celery.exceptions import Retry


# Celery rate limits are per worker instance and not a global rate limit.
# https://docs.celeryproject.org/en/stable/userguide/tasks.html#Task.rate_limit
# This queue is consumed by 6 Celery instances with 4 workers in production.
# The maximum throughput is therefore 6 instances * 4 workers * 30 tasks = 720 tasks / minute
# if we set rate_limit="30/m" on the Celery task
@notify_celery.task(
    bind=True,
    name="process-ses-result",
    max_retries=5,
    default_retry_delay=300,
)
@statsd(namespace="tasks")
def process_ses_results(self, response):  # noqa: C901
    # initialize these to None so error handling is simpler
    notification = None
    reference = None
    notification_status = None

    try:
        ses_message = json.loads(response["Message"])
        notification_type = ses_message["notificationType"]

        try:
            if notification_type == "Complaint":
                _check_and_queue_complaint_callback_task(*handle_complaint(ses_message))
                return True

            reference = ses_message["mail"]["messageId"]
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            try:
                current_app.logger.warning(
                    f"RETRY {self.request.retries}: notification not found for SES reference {reference}. "
                    f"Callback may have arrived before notification was persisted to the DB. Adding task to retry queue"
                )
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(f"notification not found for SES reference: {reference}. Giving up.")
            return
        except Exception as e:
            try:
                current_app.logger.warning(
                    f"RETRY {self.request.retries}: notification not found for SES reference {reference}. "
                    f"There was an Error: {e}. Adding task to retry queue"
                )
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(
                    f"notification not found for SES reference: {reference}. Error has persisted > number of retries. Giving up."
                )
            return

        aws_response_dict = get_aws_responses(ses_message)
        notification_status = aws_response_dict["notification_status"]
        # Sometimes we get callback from the providers in the wrong order. If the notification has a
        # permanent failure status, we don't want to overwrite it with a delivered status.
        if notification.status == NOTIFICATION_PERMANENT_FAILURE and notification_status == NOTIFICATION_DELIVERED:
            pass
        else:
            notifications_dao._update_notification_status(
                notification=notification,
                status=notification_status,
                provider_response=aws_response_dict.get("provider_response", None),
                bounce_response=aws_response_dict.get("bounce_response", None),
            )

        service_id = notification.service_id
        # Flags if seeding has occurred. Since we seed after updating the notification status in the DB then the current notification
        # is included in the fetch_notification_status_for_service_for_day call below, thus we don't need to increment the count.
        notifications_to_seed = None
        # Check if we have already seeded the annual limit counts for today
        if current_app.config["FF_ANNUAL_LIMIT"]:
            if not annual_limit_client.was_seeded_today(service_id):
                annual_limit_client.set_seeded_at(service_id)
                notifications_to_seed = fetch_notification_status_for_service_for_day(
                    datetime.now(timezone.utc),
                    service_id=service_id,
                )
                annual_limit_client.seed_annual_limit_notifications(
                    service_id, prepare_notification_counts_for_seeding(notifications_to_seed)
                )

        if not aws_response_dict["success"]:
            current_app.logger.info(
                "SES delivery failed: notification id {} and reference {} has error found. Status {}".format(
                    notification.id, reference, aws_response_dict["message"]
                )
            )
            if current_app.config["FF_ANNUAL_LIMIT"]:
                # Only increment if we didn't just seed.
                if notifications_to_seed is None:
                    annual_limit_client.increment_email_failed(notification.service_id)
                current_app.logger.info(
                    f"Incremented email_failed count in Redis. Service: {notification.service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
                )
        else:
            current_app.logger.info(
                "SES callback return status of {} for notification: {}".format(notification_status, notification.id)
            )
            if current_app.config["FF_ANNUAL_LIMIT"]:
                # Only increment if we didn't just seed.
                if notifications_to_seed is None:
                    annual_limit_client.increment_email_delivered(notification.service_id)
                current_app.logger.info(
                    f"Incremented email_delivered count in Redis. Service: {notification.service_id} Notification: {notification.id} current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
                )

        statsd_client.incr("callback.ses.{}".format(notification_status))

        if notification_status == NOTIFICATION_PERMANENT_FAILURE:
            bounce_rate_client.set_sliding_hard_bounce(notification.service_id, str(notification.id))
            current_app.logger.info(
                f"Setting total hard bounce notifications for service {notification.service.id} with notification {notification.id} in REDIS"
            )

        if notification.sent_at:
            statsd_client.timing_with_dates("callback.ses.elapsed-time", datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        notifcation_msg = "Notification ID: {}".format(notification.id) if notification else "No notification"
        notification_status_msg = (
            "Notification status: {}".format(notification_status) if notification_status else "No notification status"
        )
        ref_msg = "Reference ID: {}".format(reference) if reference else "No reference"

        current_app.logger.exception(
            "Error processing SES results: {} [{}, {}, {}]".format(type(e), notifcation_msg, notification_status_msg, ref_msg)
        )
        self.retry(queue=QueueNames.RETRY)

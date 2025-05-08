import json
import time
from datetime import datetime

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.orm.exc import NoResultFound

from app import annual_limit_client, bounce_rate_client, notify_celery, statsd_client
from app.annual_limit_utils import get_annual_limit_notifications_v2
from app.config import QueueNames
from app.dao import notifications_dao
from app.models import NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE
from app.notifications.callbacks import _check_and_queue_callback_task
from app.notifications.notifications_ses_callback import (
    _check_and_queue_complaint_callback_task,
    get_aws_responses,
    handle_complaint,
)
from celery.exceptions import Retry


def handle_complaints_and_extract_ref_ids(messages):
    """Processes the current batch of notification receipts. Handles complaints, removing them from the batch
       and returning the remaining messages for further processing.

    Args:
        messages (List): List of SES messages received from the SQS receipt buffer queue.

    Returns:
        Tuple: A tuple containing a list of notification reference IDs and a reduced list of SES messages not containing any complaint receipts.
    """
    ref_ids = []
    complaint_free_messages = []
    current_app.logger.info(f"[batch-celery] - Received: {len(messages)} receipts from Lambda.. beginning processing")
    for message in messages:
        notification_type = message["notificationType"]
        if notification_type == "Complaint":
            current_app.logger.info(f"[batch-celery] - Handling complaint: {message}")
            _check_and_queue_complaint_callback_task(*handle_complaint(message))
        else:
            ref_ids.append(message["mail"]["messageId"])
            complaint_free_messages.append(message)
    current_app.logger.info(f"[batch-celery] - Complaints handled, processing: {len(complaint_free_messages)} remaining receipts")
    return ref_ids, complaint_free_messages


def prepare_updates_and_retries(ses_messages, notifications):
    """Prepares a list of updates and retries for the notifications based on the SES receipts received.

    Args:
        ses_messages (List): The SES receipts received from the SQS queue. Should not contain any complaint receipts.
        notifications (List): A list of notifications fetched by referenceId which currently exist in the DB and can be updated.

    Returns:
        Tuple: A tuple containing:
        - updates (List): A list of dictionaries containing the notification to update, the new status, and the provider response.
        - retries (List): A list of SES messages that need to be retried.
        - notification_receipt_pairs (List): A list of tuples with the notifications mapped to their receipts update limits in Redis faster.
    """
    retries, updates, notification_receipt_pairs = [], [], []
    # Since the ses_message order and order of notifications from the DB may not be in sync,
    # lets map notifications to their references for faster lookup
    notification_map = {n.reference: n for n in notifications}

    # Prepare updates and retries
    for message in ses_messages:
        message_id = message["mail"]["messageId"]
        notification = notification_map.get(message_id)

        # If we received the callback before the notification was persisted to the DB, we need to retry
        if not notification:
            retries.append(message)
            continue

        aws_response_dict = get_aws_responses(message)
        new_status = aws_response_dict["notification_status"]

        # Sometimes we get callbacks from the provider in the "wrong" order. If the notification was already marked
        # as permanent failure, we don't want to overwrite it with a delivered status.
        if not (notification.status == NOTIFICATION_PERMANENT_FAILURE and new_status == NOTIFICATION_DELIVERED):
            updates.append(
                {
                    "notification": notification,
                    "new_status": new_status,
                    "provider_response": aws_response_dict.get("provider_response", None),
                    "bounce_response": aws_response_dict.get("bounce_response", None),
                }
            )
            notification_receipt_pairs.append((notification, aws_response_dict))

    return updates, retries, notification_receipt_pairs


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
def process_ses_results(self, response):
    messages = response.get("Messages", None)
    message = response.get("Message", None)

    if messages:
        current_app.logger.info(
            f"[batch-celery] Received batch of SES receipts, forwarding to batched_process_ses_results: {messages}"
        )
        return batched_process_ses_results(self, response)
    elif message:
        current_app.logger.info(
            f"[batch-celery] Received single SES receipt, forwarding to unbatched_process_ses_results: {message}"
        )
        return unbatched_process_ses_results(self, response)


@statsd(namespace="tasks")
def batched_process_ses_results(self, response):
    start_time = time.time()  # TODO : Remove after benchmarking
    current_app.logger.info(f"[batch-celery] - Received SES receipts: {response}")
    receipts = response["Messages"]
    try:
        # Queue complaint callbacks, filtering them out of the original list then get the ref_ids of the remaining receipts
        ref_ids, ses_messages = handle_complaints_and_extract_ref_ids(receipts)

        # If the batch of receipts were all complaints, we can return early after handling them
        if not ses_messages:
            return True

        try:
            notifications = notifications_dao.dao_get_notifications_by_references(ref_ids)
        except NoResultFound:
            try:
                current_app.logger.warning(
                    f"RETRY {self.request.retries}: no notifications found for SES references: {", ".join(ref_ids)}. "
                    f"Callbacks may have arrived before notifications were persisted to the DB. Adding task to retry queue"
                )
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(f"notifications not found for SES references: {", ".join(ref_ids)}. Giving up.")
            return
        except Exception as e:
            try:
                current_app.logger.warning(
                    f"RETRY {self.request.retries}: notification not found for SES reference {ref_ids}. "
                    f"There was an Error: {e}. Adding task to retry queue"
                )
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(
                    f"notification not found for SES reference: {ref_ids}. Error has persisted > number of retries. Giving up."
                )
            return

        updates, retries, notification_receipt_pairs = prepare_updates_and_retries(ses_messages, notifications)
        current_app.logger.info(f"[batch-celery] - Receipts to update: {len(updates)}")
        current_app.logger.info(f"[batch-celery] - Receipts to retry: {len(retries)}")

        # Update notifications
        notifications_dao._update_notification_statuses(updates)

        # Queue retries
        if retries:
            retry_ids = ", ".join([msg["mail"]["messageId"] for msg in retries])

            try:
                current_app.logger.warning(
                    f"RETRY {self.request.retries}: notifications not found for SES references {retry_ids}. "
                    f"Callback may have arrived before notification was persisted to the DB. Adding task to retry queue"
                )
                current_app.logger.info(f"[batch-celery] - Queuing retries for ids: {retry_ids} receipts")
                self.retry(queue=QueueNames.RETRY, args=[{"Messages": retries}])
            except self.MaxRetriesExceededError:
                current_app.logger.warning(
                    f"Notifications not found for SES references: {retry_ids}. Max retries exceeded. Giving up."
                )

        # Fetch once instead of repeatedly
        ff_annual_limit = current_app.config["FF_ANNUAL_LIMIT"]

        # Update annual limits based on the notifications which were updated from this batch of receipts excluding retries.
        for notification, aws_response_dict in notification_receipt_pairs:
            service_id = notification.service_id
            new_status = aws_response_dict["notification_status"]
            is_success = aws_response_dict["success"]
            log_prefix = (
                f"SES callback for notification {notification.id} reference {notification.reference} for service {service_id}: "
            )

            # Check if we have already seeded the annual limit counts for today, if we have we do not need to increment later on.
            # We seed AFTER updating the notification status, thus the current notification will already be counted.
            if ff_annual_limit:
                seeded_today = None
                if not annual_limit_client.was_seeded_today(service_id):
                    seeded_today = get_annual_limit_notifications_v2(service_id)

            if not is_success:
                current_app.logger.info(f"{log_prefix} Delivery failed with error: {aws_response_dict["message"]}")

                if ff_annual_limit and not seeded_today:
                    annual_limit_client.increment_email_failed(notification.service_id)
                    current_app.logger.info(
                        f"Incremented email_failed count in Redis. Service: {service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
                    )
            else:
                current_app.logger.info(
                    f"{log_prefix} Delivery status: {new_status}" "SES callback return status of {} for notification: {}".format(
                        new_status, notification.id
                    )
                )

                if ff_annual_limit and not seeded_today:
                    annual_limit_client.increment_email_delivered(service_id)
                    current_app.logger.info(
                        f"Incremented email_delivered count in Redis. Service: {service_id} Notification: {notification.id} current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
                    )

            statsd_client.incr("callback.ses.{}".format(new_status))

            if new_status == NOTIFICATION_PERMANENT_FAILURE:
                bounce_rate_client.set_sliding_hard_bounce(service_id, str(notification.id))
                current_app.logger.info(
                    f"Setting total hard bounce notifications for service {service_id} with notification {notification.id} in REDIS"
                )

            if notification.sent_at:
                statsd_client.timing_with_dates("callback.ses.elapsed-time", datetime.utcnow(), notification.sent_at)

            _check_and_queue_callback_task(notification)

        # TODO: remove this after benchmarking
        end_time = time.time()
        current_app.logger.info(f"[batch-celery] - process_ses_results took {end_time - start_time} seconds")

        return True

    except Retry:
        # TODO: remove this after benchmarking
        end_time = time.time()
        current_app.logger.info(f"[batch-celery] - process_ses_results took {end_time - start_time} seconds")
        raise

    except Exception:
        current_app.logger.exception(
            f"Error processing SES results for receipt batch messageId {response['MessageId']}: notification references {", ".join(ref_ids)}"
        )

        end_time = time.time()
        current_app.logger.info(f"[batch-celery] - process_ses_results took {end_time - start_time} seconds")
        self.retry(queue=QueueNames.RETRY, args=[{"Messages": updates}])


@statsd(namespace="tasks")
def unbatched_process_ses_results(self, response):  # noqa: C901
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
                notifications_to_seed = get_annual_limit_notifications_v2(service_id)

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

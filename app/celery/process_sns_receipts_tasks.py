from datetime import datetime

from flask import current_app, json
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone
from sqlalchemy.orm.exc import NoResultFound

from app import annual_limit_client, notify_celery, statsd_client
from app.config import QueueNames
from app.dao import notifications_dao
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_service_for_day,
)
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    SNS_PROVIDER,
)
from app.notifications.callbacks import _check_and_queue_callback_task
from app.utils import prepare_notification_counts_for_seeding
from celery.exceptions import Retry


# TODO: FF_ANNUAL_LIMIT removal: Temporarily ignore complexity
# flake8: noqa: C901
@notify_celery.task(bind=True, name="process-sns-result", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_sns_results(self, response):
    try:
        # Payload details: https://docs.aws.amazon.com/sns/latest/dg/sms_stats_cloudwatch.html
        sns_message = json.loads(response["Message"])
        reference = sns_message["notification"]["messageId"]
        sns_status = sns_message["status"]
        provider_response = sns_message["delivery"]["providerResponse"]

        notification_status = determine_status(sns_status, provider_response)
        if not notification_status:
            current_app.logger.warning(f"unhandled provider response for reference {reference}, received '{provider_response}'")
            notification_status = NOTIFICATION_TECHNICAL_FAILURE  # revert to tech failure by default

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            try:
                current_app.logger.warning(
                    f"RETRY {self.request.retries}: notification not found for SNS reference {reference} (update to {notification_status}). "
                    f"Callback may have arrived before notification was persisted to the DB. Adding task to retry queue"
                )
                self.retry(queue=QueueNames.RETRY)
            except self.MaxRetriesExceededError:
                current_app.logger.warning(
                    f"notification not found for SNS reference: {reference} (update to {notification_status}). Giving up."
                )
            return
        if notification.sent_by != SNS_PROVIDER:
            current_app.logger.exception(f"SNS callback handled notification {notification.id} not sent by SNS")
            return

        if notification.status != NOTIFICATION_SENT:
            notifications_dao._duplicate_update_warning(notification, notification_status)
            return

        notifications_dao._update_notification_status(
            notification=notification,
            status=notification_status,
            provider_response=provider_response,
        )

        service_id = notification.service_id
        # Check if we have already seeded the annual limit counts for today
        if current_app.config["FF_ANNUAL_LIMIT"]:
            if not annual_limit_client.was_seeded_today(service_id):
                annual_limit_client.set_seeded_at(service_id)
                todays_deltas = fetch_notification_status_for_service_for_day(
                    convert_utc_to_local_timezone(datetime.utcnow()),
                    service_id=service_id,
                )
                annual_limit_client.seed_annual_limit_notifications(
                    service_id, prepare_notification_counts_for_seeding(todays_deltas)
                )

        if notification_status != NOTIFICATION_DELIVERED:
            current_app.logger.info(
                (
                    f"SNS delivery failed: notification id {notification.id} and reference {reference} has error found. "
                    f"Provider response: {sns_message['delivery']['providerResponse']}"
                )
            )
            # TODO FF_ANNUAL_LIMIT removal
            if current_app.config["FF_ANNUAL_LIMIT"]:
                annual_limit_client.increment_sms_failed(notification.service_id)
                current_app.logger.info(
                    f"Incremented sms_failed count in Redis. Service: {notification.service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
                )
        else:
            current_app.logger.info(f"SNS callback return status of {notification_status} for notification: {notification.id}")
            # TODO FF_ANNUAL_LIMIT removal
            if current_app.config["FF_ANNUAL_LIMIT"]:
                annual_limit_client.increment_sms_delivered(notification.service_id)
                current_app.logger.info(
                    f"Incremented sms_delivered count in Redis. Service: {notification.service_id} Notification: {notification.id} Current counts: {annual_limit_client.get_all_notification_counts(notification.service_id)}"
                )

        statsd_client.incr(f"callback.sns.{notification_status}")

        if notification.sent_at:
            statsd_client.timing_with_dates("callback.sns.elapsed-time", datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True

    except Retry:
        raise

    except Exception as e:
        current_app.logger.exception(f"Error processing SNS results: {str(e)}")
        self.retry(queue=QueueNames.RETRY)


def determine_status(sns_status, provider_response):
    if sns_status == "SUCCESS":
        return NOTIFICATION_DELIVERED

    # See all the possible provider responses
    # https://docs.aws.amazon.com/sns/latest/dg/sms_stats_cloudwatch.html#sms_stats_delivery_fail_reasons
    reasons = {
        "Blocked as spam by phone carrier": NOTIFICATION_TECHNICAL_FAILURE,
        "Destination is on a blocked list": NOTIFICATION_TECHNICAL_FAILURE,
        "Invalid phone number": NOTIFICATION_TECHNICAL_FAILURE,
        "Message body is invalid": NOTIFICATION_TECHNICAL_FAILURE,
        "Phone carrier has blocked this message": NOTIFICATION_TECHNICAL_FAILURE,
        "Phone carrier is currently unreachable/unavailable": NOTIFICATION_TEMPORARY_FAILURE,
        "Phone has blocked SMS": NOTIFICATION_TECHNICAL_FAILURE,
        "Phone is on a blocked list": NOTIFICATION_TECHNICAL_FAILURE,
        "Phone is currently unreachable/unavailable": NOTIFICATION_PERMANENT_FAILURE,
        "Phone number is opted out": NOTIFICATION_PERMANENT_FAILURE,
        "This delivery would exceed max price": NOTIFICATION_TECHNICAL_FAILURE,
        "Unknown error attempting to reach phone": NOTIFICATION_TECHNICAL_FAILURE,
    }

    status = reasons.get(provider_response)  # could be None
    if not status:
        # TODO: Pattern matching in Python 3.10 should simplify this overall function logic.
        if "is opted out" in provider_response:
            return NOTIFICATION_PERMANENT_FAILURE

    return status

from datetime import datetime

from flask import current_app
from notifications_utils.recipients import RecipientCSV
from notifications_utils.template import Template

from app.aws.s3 import get_job_from_s3
from app.dao.templates_dao import dao_get_template_by_id
from app.email_limit_utils import decrement_todays_email_count
from app.models import EMAIL_TYPE, KEY_TYPE_TEST, SMS_TYPE, Job
from app.notifications.process_notifications import csv_has_simulated_and_non_simulated_recipients
from app.sms_fragment_utils import (
    decrement_todays_requested_sms_billable_units_count,
    decrement_todays_requested_sms_count,
)


def release_daily_limit_for_cancelled_job(job: Job) -> None:
    """
    Reverse the daily limit increment that was made when a scheduled job was created
    (see `create_job` in app/job/rest.py and `post_bulk` in app/v2/notifications/post_notifications.py).

    The daily counts are stored in Redis keys scoped to the current UTC date, so we only
    decrement when the original increment was made into today's key.
    """
    today = datetime.utcnow().date()
    if job.created_at.date() != today:
        return

    template_type = job.template.template_type
    if template_type == EMAIL_TYPE:
        # Email jobs are only counted at creation when scheduled for the same day.
        if job.scheduled_for is None or job.scheduled_for.date() <= today:
            decrement_todays_email_count(job.service_id, job.notification_count)
    elif template_type == SMS_TYPE:
        _release_sms_daily_limit(job)


def _release_sms_daily_limit(job: Job) -> None:
    # SMS jobs are counted at creation regardless of the scheduled date, but not for test keys or simulated recipients.
    if job.api_key is not None and job.api_key.key_type == KEY_TYPE_TEST:
        return

    try:
        template = dao_get_template_by_id(job.template_id, job.template_version)
        recipient_csv = RecipientCSV(
            get_job_from_s3(str(job.service_id), str(job.id)),
            template_type=SMS_TYPE,
            placeholders=template._as_utils_template().placeholders,
            template=Template(template.__dict__),
        )
        requested_recipients = [row["phone_number"].data for row in recipient_csv.rows]
        has_simulated, has_real_recipients = csv_has_simulated_and_non_simulated_recipients(requested_recipients, "sms")
        if has_simulated or not has_real_recipients:
            return

        # TODO FF_USE_BILLABLE_UNITS removal - Decrement billable units when feature flag is enabled
        if current_app.config.get("FF_USE_BILLABLE_UNITS"):
            decrement_todays_requested_sms_billable_units_count(job.service_id, recipient_csv.sms_fragment_count)
        else:
            decrement_todays_requested_sms_count(job.service_id, len(recipient_csv))
    except Exception:
        current_app.logger.exception(f"Could not release SMS daily limit for cancelled job {job.id}")

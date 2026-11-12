from datetime import datetime

from flask import current_app

from app.email_limit_utils import decrement_todays_email_count
from app.models import EMAIL_TYPE, KEY_TYPE_TEST, SMS_TYPE, Job
from app.sms_fragment_utils import (
    decrement_todays_requested_sms_billable_units_count,
    decrement_todays_requested_sms_count,
)


def release_daily_limit_for_cancelled_job(job: Job) -> None:
    """
    Remove a cancelled scheduled job from today's daily limit count.

    A scheduled job counts towards the daily limit of the day it's scheduled for: when it's created if that's the
    same day (see `create_job` in app/job/rest.py and `post_bulk` in app/v2/notifications/post_notifications.py),
    or when that day's count is loaded from the database (see `fetch_todays_total_email_count` and
    `fetch_todays_total_sms_count` in app/dao/services_dao.py). So it's only in today's count if it's scheduled for today.
    """
    if job.scheduled_for is None or job.scheduled_for.date() != datetime.utcnow().date():
        return
    if job.api_key is not None and job.api_key.key_type == KEY_TYPE_TEST:
        return

    template_type = job.template.template_type
    if template_type == EMAIL_TYPE:
        decrement_todays_email_count(job.service_id, job.notification_count)
    elif template_type == SMS_TYPE:
        # 0 if the job has simulated recipients, null if it was created before billable_units was added (it was
        # counted on the day it was created): either way it isn't in today's count.
        if not job.billable_units:
            return
        # TODO FF_USE_BILLABLE_UNITS removal - Decrement billable units when feature flag is enabled
        if current_app.config.get("FF_USE_BILLABLE_UNITS"):
            decrement_todays_requested_sms_billable_units_count(job.service_id, job.billable_units)
        else:
            decrement_todays_requested_sms_count(job.service_id, job.notification_count)

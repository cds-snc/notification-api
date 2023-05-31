from datetime import datetime

from app import create_uuid
from app.aws.mocks import (
    ses_hard_bounce_callback,
    ses_notification_callback,
    ses_soft_bounce_callback,
    sns_failed_callback,
    sns_success_callback,
)
from app.celery.process_ses_receipts_tasks import process_ses_results
from app.celery.process_sns_receipts_tasks import process_sns_results
from app.config import QueueNames

temp_fail = "+15149301633"
perm_fail = "+15149301632"
delivered = "+15149301631"

delivered_email = "delivered@simulator.notify"
perm_fail_email = "perm-fail@simulator.notify"
temp_fail_email = "temp-fail@simulator.notify"


def send_sms_response(provider, to, reference=None):
    reference = reference or str(create_uuid())
    body = aws_sns_callback(reference, to)
    process_sns_results.apply_async([body], queue=QueueNames.RESEARCH_MODE)
    return reference


def send_email_response(to, reference=None):
    if not reference:
        reference = str(create_uuid())
    if to == perm_fail_email:
        body = ses_hard_bounce_callback(reference)
    elif to == temp_fail_email:
        body = ses_soft_bounce_callback(reference)
    else:
        body = ses_notification_callback(reference)

    process_ses_results.apply_async([body], queue=QueueNames.RESEARCH_MODE)
    return reference


def aws_sns_callback(notification_id, to):
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    if to.strip().endswith(perm_fail):
        return sns_failed_callback(
            "Phone is currently unreachable/unavailable", notification_id, destination=to, timestamp=timestamp
        )
    elif to.strip().endswith(temp_fail):
        return sns_failed_callback(
            "Phone carrier is currently unreachable/unavailable", notification_id, destination=to, timestamp=timestamp
        )
    else:
        return sns_success_callback(notification_id, destination=to, timestamp=timestamp)

import random
from datetime import datetime, timedelta

from flask import current_app
from notifications_utils.s3 import s3upload

from app import create_uuid, notify_celery
from app.aws.mocks import (
    pinpoint_failed_callback,
    pinpoint_successful_callback,
    ses_hard_bounce_callback,
    ses_notification_callback,
    ses_soft_bounce_callback,
    sns_failed_callback,
    sns_s3_callback,
    sns_success_callback,
)
from app.aws.s3 import file_exists
from app.celery.process_pinpoint_receipts_tasks import process_pinpoint_results
from app.celery.process_ses_receipts_tasks import process_ses_results
from app.celery.process_sns_receipts_tasks import process_sns_results
from app.config import QueueNames
from app.models import PINPOINT_PROVIDER, SNS_PROVIDER

temp_fail = "+15149301633"
perm_fail = "+15149301632"
delivered = "+15149301631"

delivered_email = "delivered@simulator.notify"
perm_fail_email = "perm-fail@simulator.notify"
temp_fail_email = "temp-fail@simulator.notify"


def send_sms_response(provider, to, reference=None):
    reference = reference or str(create_uuid())
    if provider == SNS_PROVIDER:
        body = aws_sns_callback(reference, to)
        process_sns_results.apply_async([body], queue=QueueNames.RESEARCH_MODE)
    elif provider == PINPOINT_PROVIDER:
        body = aws_pinpoint_callback(reference, to)
        process_pinpoint_results.apply_async([body], queue=QueueNames.RESEARCH_MODE)
    else:
        raise ValueError("Provider {} not supported".format(provider))
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


def aws_pinpoint_callback(notification_id, to):
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    if to.strip().endswith(perm_fail):
        return pinpoint_failed_callback(
            "Phone is currently unreachable/unavailable", notification_id, destination=to, timestamp=timestamp
        )
    elif to.strip().endswith(temp_fail):
        return pinpoint_failed_callback(
            "Phone carrier is currently unreachable/unavailable", notification_id, destination=to, timestamp=timestamp
        )
    else:
        return pinpoint_successful_callback(notification_id, destination=to, timestamp=timestamp)


@notify_celery.task(
    bind=True,
    name="create-fake-letter-response-file",
    max_retries=5,
    default_retry_delay=300,
)
def create_fake_letter_response_file(self, reference):
    now = datetime.utcnow()
    dvla_response_data = "{}|Sent|0|Sorted".format(reference)

    # try and find a filename that hasn't been taken yet - from a random time within the last 30 seconds
    for i in sorted(range(30), key=lambda _: random.random()):
        upload_file_name = "NOTIFY-{}-RSP.TXT".format((now - timedelta(seconds=i)).strftime("%Y%m%d%H%M%S"))
        if not file_exists(current_app.config["DVLA_RESPONSE_BUCKET_NAME"], upload_file_name):
            break
    else:
        raise ValueError(
            "cant create fake letter response file for {} - too many files for that time already exist on s3".format(reference)
        )

    s3upload(
        filedata=dvla_response_data,
        region=current_app.config["AWS_REGION"],
        bucket_name=current_app.config["DVLA_RESPONSE_BUCKET_NAME"],
        file_location=upload_file_name,
    )
    current_app.logger.info(
        "Fake DVLA response file {}, content [{}], uploaded to {}, created at {}".format(
            upload_file_name,
            dvla_response_data,
            current_app.config["DVLA_RESPONSE_BUCKET_NAME"],
            now,
        )
    )

    # on development we can't trigger SNS callbacks so we need to manually hit the DVLA callback endpoint
    if current_app.config["NOTIFY_ENVIRONMENT"] == "development":
        body = sns_s3_callback(upload_file_name, reference)
        process_sns_results.apply_async([body], queue=QueueNames.RESEARCH_MODE)

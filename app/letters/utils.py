import io
import math
from datetime import datetime, timedelta
from enum import Enum

import boto3
from flask import current_app

from notifications_utils.letter_timings import LETTER_PROCESSING_DEADLINE
from notifications_utils.pdf import pdf_page_count
from notifications_utils.s3 import s3upload
from notifications_utils.timezones import convert_utc_to_local_timezone

from app.models import KEY_TYPE_TEST, SECOND_CLASS, RESOLVE_POSTAGE_FOR_FILE_NAME, NOTIFICATION_VALIDATION_FAILED


class ScanErrorType(Enum):
    ERROR = 1
    FAILURE = 2


LETTERS_PDF_FILE_LOCATION_STRUCTURE = '{folder}NOTIFY.{reference}.{duplex}.{letter_class}.{colour}.{crown}.{date}.pdf'

PRECOMPILED_BUCKET_PREFIX = '{folder}NOTIFY.{reference}'


def get_folder_name(
    _now,
    is_test_or_scan_letter=False,
):
    if is_test_or_scan_letter:
        folder_name = ''
    else:
        print_datetime = convert_utc_to_local_timezone(_now)
        if print_datetime.time() > LETTER_PROCESSING_DEADLINE:
            print_datetime += timedelta(days=1)
        folder_name = '{}/'.format(print_datetime.date())
    return folder_name


def get_letter_pdf_filename(
    reference,
    crown,
    is_scan_letter=False,
    postage=SECOND_CLASS,
):
    now = datetime.utcnow()

    upload_file_name = LETTERS_PDF_FILE_LOCATION_STRUCTURE.format(
        folder=get_folder_name(now, is_scan_letter),
        reference=reference,
        duplex='D',
        letter_class=RESOLVE_POSTAGE_FOR_FILE_NAME[postage],
        colour='C',
        crown='C' if crown else 'N',
        date=now.strftime('%Y%m%d%H%M%S'),
    ).upper()

    return upload_file_name


def get_bucket_name_and_prefix_for_notification(notification):
    folder = ''
    if notification.status == NOTIFICATION_VALIDATION_FAILED:
        bucket_name = current_app.config['INVALID_PDF_BUCKET_NAME']
    elif notification.key_type == KEY_TYPE_TEST:
        bucket_name = current_app.config['TEST_LETTERS_BUCKET_NAME']
    else:
        bucket_name = current_app.config['LETTERS_PDF_BUCKET_NAME']
        if notification.sent_at:
            folder = '{}/'.format(notification.sent_at.date())
        elif notification.updated_at:
            folder = get_folder_name(notification.updated_at, False)
        else:
            folder = get_folder_name(notification.created_at, False)

    upload_file_name = PRECOMPILED_BUCKET_PREFIX.format(folder=folder, reference=notification.reference).upper()

    return bucket_name, upload_file_name


def move_uploaded_pdf_to_letters_bucket(
    source_filename,
    upload_filename,
):
    _move_s3_object(
        source_bucket=current_app.config['TRANSIENT_UPLOADED_LETTERS'],
        source_filename=source_filename,
        target_bucket=current_app.config['LETTERS_PDF_BUCKET_NAME'],
        target_filename=upload_filename,
    )


def get_letter_pdf(notification):
    bucket_name, prefix = get_bucket_name_and_prefix_for_notification(notification)

    s3 = boto3.resource('s3')
    bucket = s3.Bucket(bucket_name)
    item = next(x for x in bucket.objects.filter(Prefix=prefix))

    obj = s3.Object(bucket_name=bucket_name, key=item.key)
    return obj.get()['Body'].read()


def _move_s3_object(
    source_bucket,
    source_filename,
    target_bucket,
    target_filename,
):
    s3 = boto3.resource('s3')
    copy_source = {'Bucket': source_bucket, 'Key': source_filename}

    target_bucket = s3.Bucket(target_bucket)
    obj = target_bucket.Object(target_filename)

    # Tags are copied across but the expiration time is reset in the destination bucket
    # e.g. if a file has 5 days left to expire on a ONE_WEEK retention in the source bucket,
    # in the destination bucket the expiration time will be reset to 7 days left to expire
    obj.copy(copy_source, ExtraArgs={'ServerSideEncryption': 'AES256'})

    s3.Object(source_bucket, source_filename).delete()

    current_app.logger.info(
        'Moved letter PDF: {}/{} to {}/{}'.format(source_bucket, source_filename, target_bucket, target_filename)
    )


def _copy_s3_object(
    source_bucket,
    source_filename,
    target_bucket,
    target_filename,
):
    s3 = boto3.resource('s3')
    copy_source = {'Bucket': source_bucket, 'Key': source_filename}

    target_bucket = s3.Bucket(target_bucket)
    obj = target_bucket.Object(target_filename)

    # Tags are copied across but the expiration time is reset in the destination bucket
    # e.g. if a file has 5 days left to expire on a ONE_WEEK retention in the source bucket,
    # in the destination bucket the expiration time will be reset to 7 days left to expire
    obj.copy(copy_source, ExtraArgs={'ServerSideEncryption': 'AES256'})

    current_app.logger.info(
        'Copied letter PDF: {}/{} to {}/{}'.format(source_bucket, source_filename, target_bucket, target_filename)
    )


def letter_print_day(created_at):
    bst_print_datetime = convert_utc_to_local_timezone(created_at) + timedelta(hours=6, minutes=30)
    bst_print_date = bst_print_datetime.date()

    current_bst_date = convert_utc_to_local_timezone(datetime.utcnow()).date()

    if bst_print_date >= current_bst_date:
        return 'today'
    else:
        print_date = bst_print_datetime.strftime('%d %B').lstrip('0')
        return 'on {}'.format(print_date)

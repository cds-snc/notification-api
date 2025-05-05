from datetime import timedelta
from enum import Enum

import boto3
from flask import current_app

from notifications_utils.letter_timings import LETTER_PROCESSING_DEADLINE
from notifications_utils.timezones import convert_utc_to_local_timezone


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

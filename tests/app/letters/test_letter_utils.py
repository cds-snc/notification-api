import pytest
from datetime import datetime

import boto3
from flask import current_app
from freezegun import freeze_time
from moto import mock_s3

from app.letters.utils import (
    get_bucket_name_and_prefix_for_notification,
    get_letter_pdf_filename,
    letter_print_day,
    ScanErrorType,
)
from app.models import SERVICE_PERMISSION_TYPES

from tests.app.db import LETTER_TYPE

FROZEN_DATE_TIME = '2018-03-14 17:00:00'


def test_get_bucket_name_and_prefix_for_notification_get_from_sent_at_date(
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(
        template=template,
        api_key=api_key,
        created_at=datetime(2019, 8, 1, 17, 35),
        sent_at=datetime(2019, 8, 2, 17, 45),
    )

    bucket, bucket_prefix = get_bucket_name_and_prefix_for_notification(notification)

    assert bucket == current_app.config['LETTERS_PDF_BUCKET_NAME']
    assert bucket_prefix == f'2019-08-02/NOTIFY.{notification.reference}'.upper()


def test_get_bucket_name_and_prefix_for_notification_from_created_at_date(
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(
        template=template,
        api_key=api_key,
        created_at=datetime(2019, 8, 1, 12, 00),
        updated_at=datetime(2019, 8, 2, 12, 00),
        sent_at=datetime(2019, 8, 3, 12, 00),
    )

    bucket, bucket_prefix = get_bucket_name_and_prefix_for_notification(notification)

    assert bucket == current_app.config['LETTERS_PDF_BUCKET_NAME']
    assert bucket_prefix == f'2019-08-03/NOTIFY.{notification.reference}'.upper()


def test_get_bucket_name_and_prefix_for_notification_invalid_notification():
    with pytest.raises(AttributeError):
        get_bucket_name_and_prefix_for_notification(None)


@pytest.mark.parametrize(
    'crown_flag,expected_crown_text',
    [
        (True, 'C'),
        (False, 'N'),
    ],
)
@freeze_time('2017-12-04 17:29:00')
def test_get_letter_pdf_filename_returns_correct_filename(notify_api, mocker, crown_flag, expected_crown_text):
    filename = get_letter_pdf_filename(reference='foo', crown=crown_flag)

    assert filename == '2017-12-04/NOTIFY.FOO.D.2.C.{}.20171204172900.PDF'.format(expected_crown_text)


@pytest.mark.parametrize(
    'postage,expected_postage',
    [
        ('second', 2),
        ('first', 1),
    ],
)
@freeze_time('2017-12-04 17:29:00')
def test_get_letter_pdf_filename_returns_correct_postage_for_filename(notify_api, postage, expected_postage):
    filename = get_letter_pdf_filename(reference='foo', crown=True, postage=postage)

    assert filename == '2017-12-04/NOTIFY.FOO.D.{}.C.C.20171204172900.PDF'.format(expected_postage)


@freeze_time('2017-12-04 17:29:00')
def test_get_letter_pdf_filename_returns_correct_filename_for_test_letters(notify_api, mocker):
    filename = get_letter_pdf_filename(reference='foo', crown='C', is_scan_letter=True)

    assert filename == 'NOTIFY.FOO.D.2.C.C.20171204172900.PDF'


@freeze_time('2017-07-07 16:30:00')
def test_letter_print_day_returns_today_if_letter_was_printed_today():
    created_at = datetime(2017, 7, 7, 12, 0)
    assert letter_print_day(created_at) == 'today'

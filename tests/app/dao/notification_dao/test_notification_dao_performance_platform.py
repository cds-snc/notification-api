from datetime import date, datetime, timedelta

from freezegun import freeze_time
import pytest

from app.dao.notifications_dao import dao_get_total_notifications_sent_per_day_for_performance_platform
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    LETTER_TYPE,
)

BEGINNING_OF_DAY = date(2016, 10, 18)
END_OF_DAY = date(2016, 10, 19)


@pytest.mark.serial
def test_get_total_notifications_filters_on_date_within_date_range(sample_template, sample_notification):
    template = sample_template()
    sample_notification(template=template, created_at=datetime(2016, 10, 17, 23, 59, 59))
    sample_notification(template=template, created_at=BEGINNING_OF_DAY)
    sample_notification(template=template, created_at=datetime(2016, 10, 18, 23, 59, 59))
    sample_notification(template=template, created_at=END_OF_DAY)

    # Requires serial or better time-boxing
    result = dao_get_total_notifications_sent_per_day_for_performance_platform(BEGINNING_OF_DAY, END_OF_DAY)

    assert result.messages_total == 2


@pytest.mark.serial
@freeze_time('2016-10-18T10:00')
def test_get_total_notifications_only_counts_api_notifications(
    sample_api_key,
    sample_template,
    sample_notification,
    sample_job,
):
    """
    The WHERE clause of the underlying query:
        created_at > 'START DATE' AND
        created_at < 'END DATE' AND
        api_key_id IS NOT NULL AND
        key_type != 'test' AND
        notification_type != 'letter';
    """

    api_key = sample_api_key()
    template = sample_template()
    job = sample_job(template)

    # Only the one with an API Key will result it counting as a notification sent
    sample_notification(template=template, one_off=True)
    sample_notification(template=template, one_off=True)
    sample_notification(template=template, job=job)
    sample_notification(template=template, job=job)
    sample_notification(template=template, api_key=api_key)

    # Requires serial or better time-boxing
    result = dao_get_total_notifications_sent_per_day_for_performance_platform(BEGINNING_OF_DAY, END_OF_DAY)

    assert result.messages_total == 1


@pytest.mark.serial
@freeze_time('2016-10-18T03:00')
def test_get_total_notifications_ignores_test_keys(sample_template, sample_notification):
    template = sample_template()

    # Creating multiple templates with normal and team keys but only 1 template
    # with a test key to test that the count ignores letters
    sample_notification(template=template, key_type=KEY_TYPE_NORMAL)
    sample_notification(template=template, key_type=KEY_TYPE_NORMAL)
    sample_notification(template=template, key_type=KEY_TYPE_TEAM)
    sample_notification(template=template, key_type=KEY_TYPE_TEAM)
    sample_notification(template=template, key_type=KEY_TYPE_TEST)

    # Requires serial or better time-boxing
    result = dao_get_total_notifications_sent_per_day_for_performance_platform(BEGINNING_OF_DAY, END_OF_DAY)

    assert result.messages_total == 4


@freeze_time('2016-10-18T10:00')
def test_get_total_notifications_ignores_letters(sample_template, sample_notification):
    sms_template = sample_template()
    email_template = sample_template(template_type=EMAIL_TYPE)
    letter_template = sample_template(template_type=LETTER_TYPE)

    # Creating multiple sms and email templates but only 1 letter template to
    # test that the count ignores letters
    sample_notification(template=sms_template)
    sample_notification(template=sms_template)
    sample_notification(template=email_template)
    sample_notification(template=email_template)
    sample_notification(template=letter_template)

    result = dao_get_total_notifications_sent_per_day_for_performance_platform(BEGINNING_OF_DAY, END_OF_DAY)

    assert result.messages_total == 4


@pytest.mark.serial
@freeze_time('2016-10-18T02:00')
def test_get_total_notifications_counts_messages_within_10_seconds(
    sample_api_key,
    sample_template,
    sample_notification,
):
    created_at = datetime.utcnow()
    template = sample_template()
    api_key = sample_api_key(service=template.service)

    sample_notification(template=template, sent_at=created_at + timedelta(seconds=5), api_key=api_key)
    sample_notification(template=template, sent_at=created_at + timedelta(seconds=10), api_key=api_key)
    sample_notification(template=template, sent_at=created_at + timedelta(seconds=15), api_key=api_key)

    # Requires serial or better time-boxing
    result = dao_get_total_notifications_sent_per_day_for_performance_platform(BEGINNING_OF_DAY, END_OF_DAY)

    assert result.messages_total == 3
    assert result.messages_within_10_secs == 2


@pytest.mark.serial
@freeze_time('2016-10-18T10:00')
def test_get_total_notifications_counts_messages_that_have_not_sent(
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    sample_notification(template=template, status='created', sent_at=None, api_key=api_key)

    # Requires serial or better time-boxing
    result = dao_get_total_notifications_sent_per_day_for_performance_platform(BEGINNING_OF_DAY, END_OF_DAY)

    assert result.messages_total == 1
    assert result.messages_within_10_secs == 0


@freeze_time('2016-10-24T10:00')
def test_get_total_notifications_returns_zero_if_no_data(notify_api):
    result = dao_get_total_notifications_sent_per_day_for_performance_platform(BEGINNING_OF_DAY, END_OF_DAY)

    assert result.messages_total == 0
    assert result.messages_within_10_secs == 0

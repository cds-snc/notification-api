from collections import defaultdict, namedtuple
from datetime import date

from flask import current_app
from freezegun import freeze_time
import pytest
from sqlalchemy import delete

from app.celery.tasks import (
    get_billing_date_in_est_from_filename,
    persist_daily_sorted_letter_counts,
    process_updates_from_file,
    record_daily_sorted_counts,
    update_letter_notifications_statuses,
)
from app.constants import LETTER_TYPE, NOTIFICATION_DELIVERED, NOTIFICATION_SENDING
from app.dao.daily_sorted_letter_dao import dao_get_daily_sorted_letter_by_billing_day
from app.exceptions import DVLAException
from app.models import DailySortedLetter, NotificationHistory
from tests.app.db import create_notification_history
from tests.conftest import set_config


@pytest.fixture
def notification_update():
    """
    Returns a namedtuple to use as the argument for the check_billable_units function
    """
    NotificationUpdate = namedtuple('NotificationUpdate', ['reference', 'status', 'page_count', 'cost_threshold'])
    return NotificationUpdate('REFERENCE_ABC', 'sent', '1', 'cost')


def test_update_letter_notifications_statuses_raises_for_invalid_format(notify_api, mocker):
    invalid_file = 'ref-foo|Sent|1|Unsorted\nref-bar|Sent|2'
    mocker.patch('app.celery.tasks.s3.get_s3_file', return_value=invalid_file)

    with pytest.raises(DVLAException) as e:
        update_letter_notifications_statuses(filename='NOTIFY-20170823160812-RSP.TXT')
    assert 'DVLA response file: {} has an invalid format'.format('NOTIFY-20170823160812-RSP.TXT') in str(e.value)


def test_update_letter_notification_statuses_when_notification_does_not_exist_updates_notification_history(
    notify_db_session,
    mocker,
    sample_template,
):
    template = sample_template(template_type=LETTER_TYPE)
    valid_file = 'ref-foo|Sent|1|Unsorted'
    mocker.patch('app.celery.tasks.s3.get_s3_file', return_value=valid_file)

    notification = create_notification_history(
        template, reference='ref-foo', status=NOTIFICATION_SENDING, billable_units=1
    )

    update_letter_notifications_statuses(filename='NOTIFY-20170823160812-RSP.TXT')

    updated_history = notify_db_session.session.get(NotificationHistory, notification.id)

    assert updated_history is not None
    assert updated_history.status == NOTIFICATION_DELIVERED


def test_update_letter_notifications_statuses_calls_with_correct_bucket_location(notify_api, mocker):
    s3_mock = mocker.patch('app.celery.tasks.s3.get_s3_object')

    with set_config(notify_api, 'NOTIFY_EMAIL_FROM_DOMAIN', 'foo.bar'):
        update_letter_notifications_statuses(filename='NOTIFY-20170823160812-RSP.TXT')
        s3_mock.assert_called_with(
            '{}-ftp'.format(current_app.config['NOTIFY_EMAIL_FROM_DOMAIN']), 'NOTIFY-20170823160812-RSP.TXT'
        )


def test_update_letter_notifications_statuses_builds_updates_from_content(notify_api, mocker):
    valid_file = 'ref-foo|Sent|1|Unsorted\nref-bar|Sent|2|Sorted'
    mocker.patch('app.celery.tasks.s3.get_s3_file', return_value=valid_file)
    update_mock = mocker.patch('app.celery.tasks.process_updates_from_file')

    update_letter_notifications_statuses(filename='NOTIFY-20170823160812-RSP.TXT')

    update_mock.assert_called_with('ref-foo|Sent|1|Unsorted\nref-bar|Sent|2|Sorted')


def test_update_letter_notifications_statuses_builds_updates_list(notify_api, mocker):
    valid_file = 'ref-foo|Sent|1|Unsorted\nref-bar|Sent|2|Sorted'
    updates = process_updates_from_file(valid_file)

    assert len(updates) == 2

    assert updates[0].reference == 'ref-foo'
    assert updates[0].status == 'Sent'
    assert updates[0].page_count == '1'
    assert updates[0].cost_threshold == 'Unsorted'

    assert updates[1].reference == 'ref-bar'
    assert updates[1].status == 'Sent'
    assert updates[1].page_count == '2'
    assert updates[1].cost_threshold == 'Sorted'


@pytest.mark.parametrize(
    'filename_date, billing_date', [('20170820230000', date(2017, 8, 20)), ('20170120230000', date(2017, 1, 20))]
)
def test_get_billing_date_in_est_from_filename(filename_date, billing_date):
    filename = 'NOTIFY-{}-RSP.TXT'.format(filename_date)
    result = get_billing_date_in_est_from_filename(filename)

    assert result == billing_date


@freeze_time('2018-01-11 09:00:00')
def test_persist_daily_sorted_letter_counts_saves_sorted_and_unsorted_values(client, notify_db_session):
    letter_counts = defaultdict(int, **{'unsorted': 5, 'sorted': 1})
    persist_daily_sorted_letter_counts(date.today(), 'test.txt', letter_counts)
    day = dao_get_daily_sorted_letter_by_billing_day(date.today())

    try:
        assert day.unsorted_count == 5
        assert day.sorted_count == 1
    finally:
        stmt = delete(DailySortedLetter).where(DailySortedLetter.file_name == 'test.txt')
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_record_daily_sorted_counts_raises_dvla_exception_with_unknown_sorted_status(
    notify_api,
    mocker,
):
    file_contents = 'ref-foo|Failed|1|invalid\nrow_2|Failed|1|MM'
    mocker.patch('app.celery.tasks.s3.get_s3_file', return_value=file_contents)
    filename = 'failed.txt'
    with pytest.raises(DVLAException) as e:
        record_daily_sorted_counts(filename=filename)

    assert 'DVLA response file: {} contains unknown Sorted status'.format(filename) in e.value.message
    assert "'mm'" in e.value.message
    assert "'invalid'" in e.value.message


def test_record_daily_sorted_counts_persists_daily_sorted_letter_count_with_no_sorted_values(
    notify_db_session,
    mocker,
):
    valid_file = 'Letter1|Sent|1|Unsorted\nLetter2|Sent|2|Unsorted'
    mocker.patch('app.celery.tasks.s3.get_s3_file', return_value=valid_file)

    record_daily_sorted_counts(filename='NOTIFY-20170823160812-RSP.TXT')

    daily_sorted_letter = dao_get_daily_sorted_letter_by_billing_day(date(2017, 8, 23))

    try:
        assert daily_sorted_letter.unsorted_count == 2
        assert daily_sorted_letter.sorted_count == 0
    finally:
        stmt = delete(DailySortedLetter).where(DailySortedLetter.id == daily_sorted_letter.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()

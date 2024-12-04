from datetime import datetime, timedelta, date

import pytest
import pytz
from sqlalchemy import delete
from unittest.mock import call, patch, PropertyMock

from flask import current_app
from freezegun import freeze_time
from notifications_utils.clients.zendesk.zendesk_client import ZendeskClient

from app.celery import nightly_tasks
from app.celery.nightly_tasks import (
    delete_dvla_response_files_older_than_seven_days,
    delete_email_notifications_older_than_retention,
    delete_inbound_sms,
    delete_letter_notifications_older_than_retention,
    delete_sms_notifications_older_than_retention,
    raise_alert_if_letter_notifications_still_sending,
    remove_letter_csv_files,
    remove_sms_email_csv_files,
    remove_transformed_dvla_files,
    s3,
    send_daily_performance_platform_stats,
    send_total_sent_notifications_to_performance_platform,
    timeout_notifications,
    letter_raise_alert_if_no_ack_file_for_zip,
)
from app.celery.service_callback_tasks import create_delivery_status_callback_data
from app.clients.performance_platform.performance_platform_client import PerformancePlatformClient
from app.config import QueueNames
from app.exceptions import NotificationTechnicalFailureException
from app.constants import (
    LETTER_TYPE,
    SMS_TYPE,
    EMAIL_TYPE,
    NOTIFICATION_STATUS_TYPES_FAILED,
)
from tests.app.aws.test_s3 import single_s3_object_stub
from tests.app.db import (
    create_service_callback_api,
    create_service_data_retention,
    create_ft_notification_status,
)
from app.models import FactNotificationStatus

from tests.app.conftest import datetime_in_past


def mock_s3_get_list_match(bucket_name, subfolder='', suffix='', last_modified=None):
    if subfolder == '2018-01-11/zips_sent':
        return ['NOTIFY.2018-01-11175007.ZIP.TXT', 'NOTIFY.2018-01-11175008.ZIP.TXT']
    if subfolder == 'root/dispatch':
        return ['root/dispatch/NOTIFY.2018-01-11175007.ACK.txt', 'root/dispatch/NOTIFY.2018-01-11175008.ACK.txt']


def mock_s3_get_list_diff(bucket_name, subfolder='', suffix='', last_modified=None):
    if subfolder == '2018-01-11/zips_sent':
        return [
            'NOTIFY.2018-01-11175007p.ZIP.TXT',
            'NOTIFY.2018-01-11175008.ZIP.TXT',
            'NOTIFY.2018-01-11175009.ZIP.TXT',
            'NOTIFY.2018-01-11175010.ZIP.TXT',
        ]
    if subfolder == 'root/dispatch':
        return ['root/disoatch/NOTIFY.2018-01-11175007p.ACK.TXT', 'root/disoatch/NOTIFY.2018-01-11175008.ACK.TXT']


@pytest.mark.serial
@freeze_time('2016-05-18T10:00:00')
def test_will_remove_csv_files_for_jobs_older_than_seven_days(mocker, sample_template, sample_job):
    """
    Jobs older than seven days are deleted, but only two day's worth (two-day window)
    """

    mocker.patch('app.celery.nightly_tasks.s3.remove_job_from_s3')

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    just_under_seven_days = seven_days_ago + timedelta(seconds=1)
    eight_days_ago = seven_days_ago - timedelta(days=1)
    nine_days_ago = eight_days_ago - timedelta(days=1)
    just_under_nine_days = nine_days_ago + timedelta(seconds=1)
    nine_days_one_second_ago = nine_days_ago - timedelta(seconds=1)

    template = sample_template()
    sample_job(template, created_at=nine_days_one_second_ago, archived=True)
    job1_to_delete = sample_job(template, created_at=eight_days_ago)
    job2_to_delete = sample_job(template, created_at=just_under_nine_days)
    dont_delete_me_1 = sample_job(template, created_at=seven_days_ago)
    sample_job(template, created_at=just_under_seven_days)

    # requires serial - query intermittently grabs more to remove than expected
    remove_sms_email_csv_files()

    assert s3.remove_job_from_s3.call_args_list == [
        call(job1_to_delete.service_id, job1_to_delete.id),
        call(job2_to_delete.service_id, job2_to_delete.id),
    ]
    assert job1_to_delete.archived
    assert not dont_delete_me_1.archived


@pytest.mark.serial
@freeze_time('2016-10-18T10:00:00')
def test_will_remove_csv_files_for_jobs_older_than_retention_period(
    mocker,
    sample_service,
    sample_template,
    sample_job,
):
    """
    Jobs older than retention period are deleted, but only two day's worth (two-day window)
    """
    mocker.patch('app.celery.nightly_tasks.s3.remove_job_from_s3')
    service_1 = sample_service()
    service_2 = sample_service()

    # Cleaned up by the associated service
    create_service_data_retention(service=service_1, notification_type=SMS_TYPE, days_of_retention=3)
    create_service_data_retention(service=service_2, notification_type=EMAIL_TYPE, days_of_retention=30)

    sms_template_service_1 = sample_template(service=service_1)
    email_template_service_1 = sample_template(service=service_1, template_type=EMAIL_TYPE)

    sms_template_service_2 = sample_template(service=service_2)
    email_template_service_2 = sample_template(service=service_2, template_type=EMAIL_TYPE)

    four_days_ago = datetime.utcnow() - timedelta(days=4)
    eight_days_ago = datetime.utcnow() - timedelta(days=8)
    thirty_one_days_ago = datetime.utcnow() - timedelta(days=31)

    job1_to_delete = sample_job(sms_template_service_1, created_at=four_days_ago)
    job2_to_delete = sample_job(email_template_service_1, created_at=eight_days_ago)
    sample_job(email_template_service_1, created_at=four_days_ago)

    sample_job(email_template_service_2, created_at=eight_days_ago)
    job3_to_delete = sample_job(email_template_service_2, created_at=thirty_one_days_ago)
    job4_to_delete = sample_job(sms_template_service_2, created_at=eight_days_ago)

    # Requires serial execution
    remove_sms_email_csv_files()

    s3.remove_job_from_s3.assert_has_calls(
        [
            call(job1_to_delete.service_id, job1_to_delete.id),
            call(job2_to_delete.service_id, job2_to_delete.id),
            call(job3_to_delete.service_id, job3_to_delete.id),
            call(job4_to_delete.service_id, job4_to_delete.id),
        ],
        any_order=True,
    )


@pytest.mark.serial
@freeze_time('2017-01-01 10:00:00')
def test_remove_csv_files_filters_by_type(mocker, sample_service, sample_template, sample_job):
    """
    Jobs older than seven days are deleted, but only two day's worth (two-day window)
    """

    mocker.patch('app.celery.nightly_tasks.s3.remove_job_from_s3')
    service = sample_service()
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)
    sms_template = sample_template(service=service, template_type=SMS_TYPE)

    eight_days_ago = datetime.utcnow() - timedelta(days=8)

    job_to_delete = sample_job(template=letter_template, created_at=eight_days_ago)
    sample_job(template=sms_template, created_at=eight_days_ago)

    remove_letter_csv_files()

    assert s3.remove_job_from_s3.call_args_list == [
        call(job_to_delete.service_id, job_to_delete.id),
    ]


def test_should_call_delete_sms_notifications_more_than_week_in_task(notify_api, mocker):
    mocked = mocker.patch('app.celery.nightly_tasks.delete_notifications_older_than_retention_by_type')
    delete_sms_notifications_older_than_retention()
    mocked.assert_called_once_with(SMS_TYPE)


def test_should_call_delete_email_notifications_more_than_week_in_task(notify_api, mocker):
    mocked_notifications = mocker.patch('app.celery.nightly_tasks.delete_notifications_older_than_retention_by_type')
    delete_email_notifications_older_than_retention()
    mocked_notifications.assert_called_once_with(EMAIL_TYPE)


def test_should_call_delete_letter_notifications_more_than_week_in_task(notify_api, mocker):
    mocked = mocker.patch('app.celery.nightly_tasks.delete_notifications_older_than_retention_by_type')
    delete_letter_notifications_older_than_retention()
    mocked.assert_called_once_with(LETTER_TYPE)


@pytest.mark.serial
def test_update_status_of_notifications_after_timeout(
    notify_api,
    notify_db_session,
    sample_template,
    sample_notification,
):
    template = sample_template()
    with notify_api.test_request_context():
        time_diff = timedelta(seconds=current_app.config.get('SENDING_NOTIFICATIONS_TIMEOUT_PERIOD') + 10)

        not1 = sample_notification(
            template=template,
            status='sending',
            created_at=datetime.utcnow() - time_diff,
        )
        not2 = sample_notification(
            template=template,
            status='created',
            created_at=datetime.utcnow() - time_diff,
        )
        not3 = sample_notification(
            template=template,
            status='pending',
            created_at=datetime.utcnow() - time_diff,
        )

        with pytest.raises(NotificationTechnicalFailureException) as e:
            timeout_notifications()

        notify_db_session.session.refresh(not1)
        notify_db_session.session.refresh(not2)
        notify_db_session.session.refresh(not3)

        assert str(not2.id) in str(e.value)
        assert not1.status == 'temporary-failure'
        assert not2.status == 'technical-failure'
        assert not3.status == 'temporary-failure'


@pytest.mark.serial
def test_not_update_status_of_notification_before_timeout(notify_api, sample_template, sample_notification):
    template = sample_template()
    with notify_api.test_request_context():
        not1 = sample_notification(
            template=template,
            status='sending',
            created_at=datetime.utcnow()
            - timedelta(seconds=current_app.config.get('SENDING_NOTIFICATIONS_TIMEOUT_PERIOD') - 10),
        )
        timeout_notifications()
        assert not1.status == 'sending'


@pytest.mark.serial
def test_should_not_update_status_of_letter_notifications(
    client,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=LETTER_TYPE)
    created_at = datetime.utcnow() - timedelta(days=5)
    not1 = sample_notification(template=template, status='sending', created_at=created_at)
    not2 = sample_notification(template=template, status='created', created_at=created_at)

    timeout_notifications()

    assert not1.status == 'sending'
    assert not2.status == 'created'


@pytest.mark.serial
def test_timeout_notifications_sends_status_update_to_service(
    client,
    sample_service,
    sample_template,
    mocker,
    sample_notification,
    notify_db_session,
):
    service = sample_service()
    template = sample_template(service=service)
    callback_api = create_service_callback_api(service=service, notification_statuses=NOTIFICATION_STATUS_TYPES_FAILED)
    callback_id = callback_api.id
    mocked = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')
    notification = sample_notification(
        template=template,
        status='sending',
        created_at=datetime.utcnow()
        - timedelta(seconds=current_app.config.get('SENDING_NOTIFICATIONS_TIMEOUT_PERIOD') + 10),
    )

    # serial-only method
    timeout_notifications()
    notify_db_session.session.refresh(notification)
    encrypted_data = create_delivery_status_callback_data(notification, callback_api)

    mocked.assert_called_with(
        args=(),
        kwargs={
            'service_callback_id': callback_id,
            'notification_id': str(notification.id),
            'encrypted_status_update': encrypted_data,
        },
        queue=QueueNames.CALLBACKS,
    )


def test_send_daily_performance_stats_calls_does_not_send_if_inactive(client, mocker):
    send_mock = mocker.patch(
        'app.celery.nightly_tasks.total_sent_notifications.send_total_notifications_sent_for_day_stats'
    )

    with patch.object(PerformancePlatformClient, 'active', new_callable=PropertyMock) as mock_active:
        mock_active.return_value = False
        send_daily_performance_platform_stats()

    assert send_mock.call_count == 0


@freeze_time('2016-06-11 02:00:00')
def test_send_total_sent_notifications_to_performance_platform_calls_with_correct_totals(
    notify_db_session,
    sample_template,
    mocker,
):
    perf_mock = mocker.patch(
        'app.celery.nightly_tasks.total_sent_notifications.send_total_notifications_sent_for_day_stats'
    )  # noqa

    today = date(2016, 6, 11)
    template1 = sample_template(template_type=SMS_TYPE)
    template2 = sample_template(template_type=EMAIL_TYPE)
    template_ids = (template1.id, template2.id)

    create_ft_notification_status(utc_date=today, template=template1)
    create_ft_notification_status(utc_date=today, template=template2)

    # Create some notifications for the day before.
    yesterday = date(2016, 6, 10)
    create_ft_notification_status(utc_date=yesterday, template=template1, count=2)
    create_ft_notification_status(utc_date=yesterday, template=template2, count=3)

    try:
        with patch.object(PerformancePlatformClient, 'active', new_callable=PropertyMock) as mock_active:
            mock_active.return_value = True
            send_total_sent_notifications_to_performance_platform(yesterday)

            perf_mock.assert_has_calls(
                [call('2016-06-10', SMS_TYPE, 2), call('2016-06-10', EMAIL_TYPE, 3), call('2016-06-10', LETTER_TYPE, 0)]
            )
    finally:
        stmt = delete(FactNotificationStatus).where(FactNotificationStatus.template_id.in_(template_ids))
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_should_call_delete_inbound_sms(notify_api, mocker):
    mocker.patch('app.celery.nightly_tasks.delete_inbound_sms_older_than_retention')
    delete_inbound_sms()
    assert nightly_tasks.delete_inbound_sms_older_than_retention.call_count == 1


@freeze_time('2017-01-01 10:00:00')
def test_remove_dvla_transformed_files_removes_expected_files(mocker, sample_service, sample_template, sample_job):
    mocker.patch('app.celery.nightly_tasks.s3.remove_transformed_dvla_file')
    service = sample_service()
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    just_under_seven_days = seven_days_ago + timedelta(seconds=1)
    just_over_seven_days = seven_days_ago - timedelta(seconds=1)
    eight_days_ago = seven_days_ago - timedelta(days=1)
    nine_days_ago = eight_days_ago - timedelta(days=1)
    ten_days_ago = nine_days_ago - timedelta(days=1)
    just_under_nine_days = nine_days_ago + timedelta(seconds=1)
    just_over_nine_days = nine_days_ago - timedelta(seconds=1)
    just_over_ten_days = ten_days_ago - timedelta(seconds=1)

    sample_job(letter_template, created_at=just_under_seven_days)
    sample_job(letter_template, created_at=just_over_seven_days)
    job_to_delete_1 = sample_job(letter_template, created_at=eight_days_ago)
    job_to_delete_2 = sample_job(letter_template, created_at=nine_days_ago)
    job_to_delete_3 = sample_job(letter_template, created_at=just_under_nine_days)
    job_to_delete_4 = sample_job(letter_template, created_at=just_over_nine_days)
    sample_job(letter_template, created_at=just_over_ten_days)
    remove_transformed_dvla_files()

    s3.remove_transformed_dvla_file.assert_has_calls(
        [
            call(job_to_delete_1.id),
            call(job_to_delete_2.id),
            call(job_to_delete_3.id),
            call(job_to_delete_4.id),
        ],
        any_order=True,
    )


def test_remove_dvla_transformed_files_does_not_remove_files(mocker, sample_service, sample_template, sample_job):
    mocker.patch('app.celery.nightly_tasks.s3.remove_transformed_dvla_file')

    service = sample_service()
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)

    yesterday = datetime.utcnow() - timedelta(days=1)
    six_days_ago = datetime.utcnow() - timedelta(days=6)
    seven_days_ago = six_days_ago - timedelta(days=1)
    just_over_nine_days = seven_days_ago - timedelta(days=2, seconds=1)

    sample_job(letter_template, created_at=yesterday)
    sample_job(letter_template, created_at=six_days_ago)
    sample_job(letter_template, created_at=seven_days_ago)
    sample_job(letter_template, created_at=just_over_nine_days)

    remove_transformed_dvla_files()

    s3.remove_transformed_dvla_file.assert_has_calls([])


@freeze_time('2016-01-01 11:00:00')
def test_delete_dvla_response_files_older_than_seven_days_removes_old_files(notify_api, mocker):
    AFTER_SEVEN_DAYS = datetime_in_past(days=8)
    single_page_s3_objects = [
        {
            'Contents': [
                single_s3_object_stub('bar/foo1.txt', AFTER_SEVEN_DAYS),
                single_s3_object_stub('bar/foo2.txt', AFTER_SEVEN_DAYS),
            ]
        }
    ]
    mocker.patch(
        'app.celery.nightly_tasks.s3.get_s3_bucket_objects', return_value=single_page_s3_objects[0]['Contents']
    )
    remove_s3_mock = mocker.patch('app.celery.nightly_tasks.s3.remove_s3_object')

    delete_dvla_response_files_older_than_seven_days()

    remove_s3_mock.assert_has_calls(
        [
            call(current_app.config['DVLA_RESPONSE_BUCKET_NAME'], single_page_s3_objects[0]['Contents'][0]['Key']),
            call(current_app.config['DVLA_RESPONSE_BUCKET_NAME'], single_page_s3_objects[0]['Contents'][1]['Key']),
        ]
    )


@freeze_time('2016-01-01 11:00:00')
def test_delete_dvla_response_files_older_than_seven_days_does_not_remove_files(notify_api, mocker):
    START_DATE = datetime_in_past(days=9)
    JUST_BEFORE_START_DATE = datetime_in_past(days=9, seconds=1)
    END_DATE = datetime_in_past(days=7)
    JUST_AFTER_END_DATE = END_DATE + timedelta(seconds=1)

    single_page_s3_objects = [
        {
            'Contents': [
                single_s3_object_stub('bar/foo1.txt', JUST_BEFORE_START_DATE),
                single_s3_object_stub('bar/foo2.txt', START_DATE),
                single_s3_object_stub('bar/foo3.txt', END_DATE),
                single_s3_object_stub('bar/foo4.txt', JUST_AFTER_END_DATE),
            ]
        }
    ]
    mocker.patch(
        'app.celery.nightly_tasks.s3.get_s3_bucket_objects', return_value=single_page_s3_objects[0]['Contents']
    )
    remove_s3_mock = mocker.patch('app.celery.nightly_tasks.s3.remove_s3_object')
    delete_dvla_response_files_older_than_seven_days()

    remove_s3_mock.assert_not_called()


@pytest.mark.serial
@freeze_time('2018-01-17 17:00:00')
def test_alert_if_letter_notifications_still_sending(sample_template, mocker, sample_notification):
    template = sample_template(template_type=LETTER_TYPE)
    two_days_ago = datetime(2018, 1, 15, 13, 30)
    sample_notification(template=template, status='sending', sent_at=two_days_ago)

    mock_create_ticket = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    # Requires serial worker or refactor
    raise_alert_if_letter_notifications_still_sending()

    mock_create_ticket.assert_called_once_with(
        subject='[test] Letters still sending',
        message="There are 1 letters in the 'sending' state from Monday 15 January",
        ticket_type=ZendeskClient.TYPE_INCIDENT,
    )


@pytest.mark.serial
def test_alert_if_letter_notifications_still_sending_a_day_ago_no_alert(sample_template, mocker, sample_notification):
    template = sample_template(template_type=LETTER_TYPE)
    today = datetime.utcnow()
    one_day_ago = today - timedelta(days=1)
    sample_notification(template=template, status='sending', sent_at=one_day_ago)

    mock_create_ticket = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    # Requires serial worker or refactor
    raise_alert_if_letter_notifications_still_sending()
    assert not mock_create_ticket.called


@pytest.mark.serial
@freeze_time('2018-01-17 17:00:00')
def test_alert_if_letter_notifications_still_sending_only_alerts_sending(sample_template, mocker, sample_notification):
    template = sample_template(template_type=LETTER_TYPE)
    two_days_ago = datetime(2018, 1, 15, 13, 30)
    sample_notification(template=template, status='sending', sent_at=two_days_ago)
    sample_notification(template=template, status='delivered', sent_at=two_days_ago)
    sample_notification(template=template, status='failed', sent_at=two_days_ago)

    mock_create_ticket = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    # Requires serial worker or refactor
    raise_alert_if_letter_notifications_still_sending()

    mock_create_ticket.assert_called_once_with(
        subject='[test] Letters still sending',
        message="There are 1 letters in the 'sending' state from Monday 15 January",
        ticket_type='incident',
    )


@freeze_time('2018-01-17 17:00:00')
def test_alert_if_letter_notifications_still_sending_alerts_for_older_than_offset(
    sample_template, mocker, sample_notification
):
    template = sample_template(template_type=LETTER_TYPE)
    three_days_ago = datetime(2018, 1, 14, 13, 30)
    sample_notification(template=template, status='sending', sent_at=three_days_ago)

    mock_create_ticket = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    raise_alert_if_letter_notifications_still_sending()

    mock_create_ticket.assert_called_once_with(
        subject='[test] Letters still sending',
        message="There are 1 letters in the 'sending' state from Monday 15 January",
        ticket_type='incident',
    )


@freeze_time('2018-01-14 17:00:00')
def test_alert_if_letter_notifications_still_sending_does_nothing_on_the_weekend(
    sample_template, mocker, sample_notification
):
    template = sample_template(template_type=LETTER_TYPE)
    yesterday = datetime(2018, 1, 13, 13, 30)
    sample_notification(template=template, status='sending', sent_at=yesterday)

    mock_create_ticket = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    raise_alert_if_letter_notifications_still_sending()

    assert not mock_create_ticket.called


@freeze_time('2018-01-15 17:00:00')
def test_monday_alert_if_letter_notifications_still_sending_reports_thursday_letters(
    mocker, sample_template, sample_notification
):
    template = sample_template(template_type=LETTER_TYPE)
    thursday = datetime(2018, 1, 11, 13, 30)
    yesterday = datetime(2018, 1, 14, 13, 30)
    sample_notification(template=template, status='sending', sent_at=thursday)
    sample_notification(template=template, status='sending', sent_at=yesterday)

    mock_create_ticket = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    raise_alert_if_letter_notifications_still_sending()

    mock_create_ticket.assert_called_once_with(
        subject='[test] Letters still sending',
        message="There are 1 letters in the 'sending' state from Thursday 11 January",
        ticket_type='incident',
    )


@freeze_time('2018-01-16 17:00:00')
def test_tuesday_alert_if_letter_notifications_still_sending_reports_friday_letters(
    sample_template, mocker, sample_notification
):
    template = sample_template(template_type=LETTER_TYPE)
    friday = datetime(2018, 1, 12, 13, 30)
    yesterday = datetime(2018, 1, 14, 13, 30)
    sample_notification(template=template, status='sending', sent_at=friday)
    sample_notification(template=template, status='sending', sent_at=yesterday)

    mock_create_ticket = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    raise_alert_if_letter_notifications_still_sending()

    mock_create_ticket.assert_called_once_with(
        subject='[test] Letters still sending',
        message="There are 1 letters in the 'sending' state from Friday 12 January",
        ticket_type='incident',
    )


@freeze_time('2018-01-11T23:00:00')
def test_letter_raise_alert_if_no_ack_file_for_zip_does_not_raise_when_files_match_zip_list(mocker, notify_db):
    mock_file_list = mocker.patch('app.aws.s3.get_list_of_files_by_suffix', side_effect=mock_s3_get_list_match)
    letter_raise_alert_if_no_ack_file_for_zip()

    yesterday = datetime.now(tz=pytz.utc) - timedelta(days=1)  # Datatime format on AWS
    subfoldername = datetime.utcnow().strftime('%Y-%m-%d') + '/zips_sent'
    assert mock_file_list.call_count == 2
    assert mock_file_list.call_args_list == [
        call(bucket_name=current_app.config['LETTERS_PDF_BUCKET_NAME'], subfolder=subfoldername, suffix='.TXT'),
        call(
            bucket_name=current_app.config['DVLA_RESPONSE_BUCKET_NAME'],
            subfolder='root/dispatch',
            suffix='.ACK.txt',
            last_modified=yesterday,
        ),
    ]


@freeze_time('2018-01-11T23:00:00')
def test_letter_raise_alert_if_ack_files_not_match_zip_list(mocker, notify_db):
    mock_file_list = mocker.patch('app.aws.s3.get_list_of_files_by_suffix', side_effect=mock_s3_get_list_diff)
    mock_zendesk = mocker.patch('app.celery.nightly_tasks.zendesk_client.create_ticket')

    letter_raise_alert_if_no_ack_file_for_zip()

    assert mock_file_list.call_count == 2

    message = (
        'Letter ack file does not contain all zip files sent. '
        'Missing ack for zip files: {}, '
        'pdf bucket: {}, subfolder: {}, '
        'ack bucket: {}'.format(
            str(['NOTIFY.2018-01-11175009', 'NOTIFY.2018-01-11175010']),
            current_app.config['LETTERS_PDF_BUCKET_NAME'],
            datetime.utcnow().strftime('%Y-%m-%d') + '/zips_sent',
            current_app.config['DVLA_RESPONSE_BUCKET_NAME'],
        )
    )
    mock_zendesk.assert_called_once_with(subject='Letter acknowledge error', message=message, ticket_type='incident')


@freeze_time('2018-01-11T23:00:00')
def test_letter_not_raise_alert_if_no_files_do_not_cause_error(mocker, notify_db):
    mock_file_list = mocker.patch('app.aws.s3.get_list_of_files_by_suffix', side_effect=None)
    letter_raise_alert_if_no_ack_file_for_zip()

    assert mock_file_list.call_count == 2

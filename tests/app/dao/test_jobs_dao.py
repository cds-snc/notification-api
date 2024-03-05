import pytest
import uuid
from app.dao.jobs_dao import (
    can_letter_job_be_cancelled,
    dao_cancel_letter_job,
    dao_create_job,
    dao_get_future_scheduled_job_by_id_and_service_id,
    dao_get_job_by_service_id_and_job_id,
    dao_get_jobs_by_service_id,
    dao_get_jobs_older_than_data_retention,
    dao_get_notification_outcomes_for_job,
    dao_set_scheduled_jobs_to_pending,
    dao_update_job,
)
from app.models import (
    EMAIL_TYPE,
    Job,
    JOB_STATUS_SCHEDULED,
    LETTER_TYPE,
    SMS_TYPE,
)
from datetime import datetime, timedelta
from freezegun import freeze_time
from functools import partial


def test_should_have_decorated_notifications_dao_functions():
    assert dao_get_notification_outcomes_for_job.__wrapped__.__name__ == 'dao_get_notification_outcomes_for_job'  # noqa


def test_should_count_of_statuses_for_notifications_associated_with_job(
    sample_template,
    sample_job,
    sample_notification,
):
    template = sample_template()
    job = sample_job(template)
    sample_notification(template=template, job=job, status='created')
    sample_notification(template=template, job=job, status='created')
    sample_notification(template=template, job=job, status='created')
    sample_notification(template=template, job=job, status='sending')
    sample_notification(template=template, job=job, status='delivered')

    results = dao_get_notification_outcomes_for_job(template.service_id, job.id)
    assert {row.status: row.count for row in results} == {
        'created': 3,
        'sending': 1,
        'delivered': 1,
    }


def test_should_return_zero_length_array_if_no_notifications_for_job(sample_service, sample_template, sample_job):
    job = sample_job(sample_template())
    assert len(dao_get_notification_outcomes_for_job(job.id, sample_service().id)) == 0


def test_should_return_notifications_only_for_this_job(sample_template, sample_notification, sample_job):
    template = sample_template()
    job_1 = sample_job(template)
    job_2 = sample_job(template)

    sample_notification(template=template, job=job_1, status='created')
    sample_notification(template=template, job=job_2, status='sent')

    results = dao_get_notification_outcomes_for_job(template.service_id, job_1.id)
    assert {row.status: row.count for row in results} == {'created': 1}


def test_should_return_notifications_only_for_this_service(
    sample_service, sample_template, sample_notification, sample_notification_with_job, sample_job
):
    other_service = sample_service()
    other_template = sample_template(service=other_service)
    other_job = sample_job(other_template)

    sample_notification(template=other_template, job=other_job)

    assert len(dao_get_notification_outcomes_for_job(sample_notification_with_job.service_id, other_job.id)) == 0
    assert len(dao_get_notification_outcomes_for_job(other_service.id, sample_notification_with_job.id)) == 0


def test_create_job(notify_db_session, sample_template):
    template = sample_template()

    job_id = uuid.uuid4()
    data = {
        'id': job_id,
        'service_id': template.service.id,
        'template_id': template.id,
        'template_version': template.version,
        'original_file_name': 'some.csv',
        'notification_count': 1,
        'created_by': template.created_by,
    }

    job = Job(**data)
    dao_create_job(job)

    job_from_db = notify_db_session.session.get(Job, job_id)

    try:
        assert isinstance(job_from_db, Job), "This shouldn't be None."
        assert job == job_from_db
        assert job_from_db.notifications_delivered == 0
        assert job_from_db.notifications_failed == 0
    finally:
        notify_db_session.session.delete(job_from_db)
        notify_db_session.session.commit()


def test_get_job_by_id(sample_template, sample_job):
    job = sample_job(sample_template())
    job_from_db = dao_get_job_by_service_id_and_job_id(job.service.id, job.id)
    assert job == job_from_db


def test_get_jobs_for_service(sample_service, sample_template, sample_job):
    one_job = sample_job(sample_template())

    other_service = sample_service()
    other_template = sample_template(service=other_service)
    other_job = sample_job(other_template)

    one_job_from_db = dao_get_jobs_by_service_id(one_job.service_id).items
    other_job_from_db = dao_get_jobs_by_service_id(other_job.service_id).items

    assert len(one_job_from_db) == 1
    assert one_job == one_job_from_db[0]

    assert len(other_job_from_db) == 1
    assert other_job == other_job_from_db[0]

    assert one_job_from_db != other_job_from_db


def test_get_jobs_for_service_with_limit_days_param(sample_template, sample_job):
    template = sample_template()
    one_job = sample_job(template)
    old_job = sample_job(template, created_at=datetime.now() - timedelta(days=8))

    jobs = dao_get_jobs_by_service_id(one_job.service_id).items

    assert len(jobs) == 2
    assert one_job in jobs
    assert old_job in jobs

    jobs_limit_days = dao_get_jobs_by_service_id(one_job.service_id, limit_days=7).items
    assert len(jobs_limit_days) == 1
    assert one_job in jobs_limit_days
    assert old_job not in jobs_limit_days


@freeze_time('2017-06-10')
# This test assumes the local timezone is EST
def test_get_jobs_for_service_with_limit_days_edge_case(sample_template, sample_job):
    template = sample_template()
    one_job = sample_job(template)
    just_after_midnight_job = sample_job(template, created_at=datetime(2017, 6, 3, 4, 0, 1))
    just_before_midnight_job = sample_job(template, created_at=datetime(2017, 6, 3, 3, 59, 0))

    jobs_limit_days = dao_get_jobs_by_service_id(one_job.service_id, limit_days=7).items
    assert len(jobs_limit_days) == 2
    assert one_job in jobs_limit_days
    assert just_after_midnight_job in jobs_limit_days
    assert just_before_midnight_job not in jobs_limit_days


def test_get_jobs_for_service_in_processed_at_then_created_at_order(
    notify_db,
    notify_db_session,
    sample_template,
    sample_job,
):
    from_hour = partial(datetime, 2001, 1, 1)
    template = sample_template()

    created_jobs = [
        sample_job(template, created_at=from_hour(2), processing_started=None),
        sample_job(template, created_at=from_hour(1), processing_started=None),
        sample_job(template, created_at=from_hour(1), processing_started=from_hour(4)),
        sample_job(template, created_at=from_hour(2), processing_started=from_hour(3)),
    ]

    jobs = dao_get_jobs_by_service_id(template.service.id).items

    assert len(jobs) == len(created_jobs)

    for index in range(0, len(created_jobs)):
        assert jobs[index].id == created_jobs[index].id


def test_update_job(notify_db_session, sample_template, sample_job):
    job = sample_job(sample_template())
    assert job.job_status == 'pending'

    job.job_status = 'in progress'
    dao_update_job(job)

    job_from_db = notify_db_session.session.get(Job, job.id)
    assert job_from_db.job_status == 'in progress'


def test_set_scheduled_jobs_to_pending_gets_all_jobs_in_scheduled_state_before_now(sample_template, sample_job):
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
    template = sample_template()
    job_new = sample_job(template, scheduled_for=one_minute_ago, job_status='scheduled')
    job_old = sample_job(template, scheduled_for=one_hour_ago, job_status='scheduled')
    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 2
    assert jobs[0].id == job_old.id
    assert jobs[1].id == job_new.id


def test_set_scheduled_jobs_to_pending_gets_ignores_jobs_not_scheduled(sample_template, sample_job):
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    job_scheduled = sample_job(sample_template(), scheduled_for=one_minute_ago, job_status='scheduled')
    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 1
    assert jobs[0].id == job_scheduled.id


def test_set_scheduled_jobs_to_pending_ignores_jobs_scheduled_in_the_future(sample_scheduled_job):
    """
    sample_scheduled_job is scheduled in the future, so this query should not return any rows.
    """

    assert sample_scheduled_job.job_status == JOB_STATUS_SCHEDULED
    assert sample_scheduled_job.scheduled_for > datetime.utcnow()

    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 0


def test_set_scheduled_jobs_to_pending_updates_rows(sample_template, sample_job):
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
    template = sample_template()
    sample_job(template, scheduled_for=one_minute_ago, job_status='scheduled')
    sample_job(template, scheduled_for=one_hour_ago, job_status='scheduled')
    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 2
    assert jobs[0].job_status == 'pending'
    assert jobs[1].job_status == 'pending'


def test_get_future_scheduled_job_gets_a_job_yet_to_send(sample_scheduled_job):
    result = dao_get_future_scheduled_job_by_id_and_service_id(sample_scheduled_job.id, sample_scheduled_job.service_id)
    assert result.id == sample_scheduled_job.id


@pytest.mark.serial
@freeze_time('1990-10-31 10:00:00')
def test_should_get_jobs_seven_days_old(sample_template, sample_job):
    """
    Jobs older than seven days are deleted, but only two day's worth (two-day window)
    """
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    within_seven_days = seven_days_ago + timedelta(seconds=1)

    eight_days_ago = seven_days_ago - timedelta(days=1)

    nine_days_ago = eight_days_ago - timedelta(days=2)
    nine_days_one_second_ago = nine_days_ago - timedelta(seconds=1)

    template = sample_template()

    sample_job(template, created_at=seven_days_ago)
    sample_job(template, created_at=within_seven_days)
    job_to_delete = sample_job(template, created_at=eight_days_ago)
    sample_job(template, created_at=nine_days_ago, archived=True)
    sample_job(template, created_at=nine_days_one_second_ago, archived=True)

    # serial - Fails intermittently
    jobs = dao_get_jobs_older_than_data_retention(notification_types=[template.template_type])

    assert len(jobs) == 1
    assert jobs[0].id == job_to_delete.id


def test_get_jobs_for_service_is_paginated(sample_service, sample_template, sample_job):
    with freeze_time('2015-01-01T00:00:00') as the_time:
        template = sample_template()

        for _ in range(10):
            the_time.tick(timedelta(hours=1))
            sample_job(template)

    res = dao_get_jobs_by_service_id(template.service.id, page=1, page_size=2)

    assert res.per_page == 2
    assert res.total == 10
    assert len(res.items) == 2
    assert res.items[0].created_at == datetime(2015, 1, 1, 10)
    assert res.items[1].created_at == datetime(2015, 1, 1, 9)

    res = dao_get_jobs_by_service_id(template.service.id, page=2, page_size=2)

    assert len(res.items) == 2
    assert res.items[0].created_at == datetime(2015, 1, 1, 8)
    assert res.items[1].created_at == datetime(2015, 1, 1, 7)


@pytest.mark.parametrize(
    'file_name',
    [
        'Test message',
        'Report',
    ],
)
def test_get_jobs_for_service_doesnt_return_test_messages(
    sample_template,
    sample_job,
    file_name,
):
    """
    The parametrized file names correspond to Job rows that should be ignored according to the
    query in app/dao/jobs_dao.py::dao_get_jobs_by_service_id.
    """

    job = sample_job(
        sample_template(),
        original_file_name=file_name,
    )

    jobs = dao_get_jobs_by_service_id(job.service_id).items
    assert isinstance(jobs, list)
    assert not jobs


@pytest.mark.serial
@freeze_time('2016-10-31 10:00:00')
def test_should_get_jobs_seven_days_old_filters_type(sample_service, sample_template, sample_job):
    eight_days_ago = datetime.utcnow() - timedelta(days=8)
    service = sample_service()
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)

    job_to_remain = sample_job(letter_template, created_at=eight_days_ago)
    sample_job(sms_template, created_at=eight_days_ago)
    sample_job(email_template, created_at=eight_days_ago)

    # serial - Fails intermittently
    jobs = dao_get_jobs_older_than_data_retention(notification_types=[EMAIL_TYPE, SMS_TYPE])

    assert len(jobs) == 2
    assert job_to_remain.id not in [job.id for job in jobs]


@pytest.mark.serial
@freeze_time('2016-03-31 10:00:00')
def test_should_get_jobs_seven_days_old_by_scheduled_for_date(sample_service, sample_template, sample_job):
    six_days_ago = datetime.utcnow() - timedelta(days=6)
    eight_days_ago = datetime.utcnow() - timedelta(days=8)
    letter_template = sample_template(service=sample_service(), template_type=LETTER_TYPE)

    sample_job(letter_template, created_at=eight_days_ago)
    sample_job(letter_template, created_at=eight_days_ago, scheduled_for=eight_days_ago)
    job_to_remain = sample_job(letter_template, created_at=eight_days_ago, scheduled_for=six_days_ago)

    # serial - Fails intermittently
    jobs = dao_get_jobs_older_than_data_retention(notification_types=[LETTER_TYPE])

    assert len(jobs) == 2
    assert job_to_remain.id not in [job.id for job in jobs]


def assert_job_stat(job, result, sent, delivered, failed):
    assert result.job_id == job.id
    assert result.original_file_name == job.original_file_name
    assert result.created_at == job.created_at
    assert result.scheduled_for == job.scheduled_for
    assert result.template_id == job.template_id
    assert result.template_version == job.template_version
    assert result.job_status == job.job_status
    assert result.service_id == job.service_id
    assert result.notification_count == job.notification_count
    assert result.sent == sent
    assert result.delivered == delivered
    assert result.failed == failed


@freeze_time('2019-06-13 13:00')
def test_dao_cancel_letter_job_cancels_job_and_returns_number_of_cancelled_notifications(
    admin_request,
    sample_letter_template,
    sample_notification,
    sample_job,
):
    job = sample_job(sample_letter_template, notification_count=1, job_status='finished')
    notification = sample_notification(template=job.template, job=job, status='created')
    result = dao_cancel_letter_job(job)
    assert result == 1
    assert notification.status == 'cancelled'
    assert job.job_status == 'cancelled'


@freeze_time('2019-06-13 13:00')
def test_can_letter_job_be_cancelled_returns_true_if_job_can_be_cancelled(
    sample_letter_template,
    sample_notification,
    sample_job,
):
    job = sample_job(sample_letter_template, notification_count=1, job_status='finished')
    sample_notification(template=job.template, job=job, status='created')
    result, errors = can_letter_job_be_cancelled(job)
    assert result
    assert not errors


@freeze_time('2019-06-13 13:00')
def test_can_letter_job_be_cancelled_returns_false_and_error_message_if_notification_status_sending(
    sample_letter_template,
    sample_notification,
    sample_job,
):
    job = sample_job(sample_letter_template, notification_count=2, job_status='finished')
    sample_notification(template=job.template, job=job, status='sending')
    sample_notification(template=job.template, job=job, status='created')
    result, errors = can_letter_job_be_cancelled(job)
    assert not result
    assert errors == 'It’s too late to cancel sending, these letters have already been sent.'


@freeze_time('2019-06-13 13:00')
def test_can_letter_job_be_cancelled_returns_false_and_error_message_if_not_a_letter_job(
    sample_template,
    sample_notification,
    sample_job,
):
    job = sample_job(sample_template(), notification_count=1, job_status='finished')
    sample_notification(template=job.template, job=job, status='created')
    result, errors = can_letter_job_be_cancelled(job)
    assert not result
    assert errors == 'Only letter jobs can be cancelled through this endpoint. This is not a letter job.'


@freeze_time('2019-06-13 13:00')
def test_can_letter_job_be_cancelled_returns_false_and_error_message_if_job_not_finished(
    sample_letter_template,
    sample_notification,
    sample_job,
):
    job = sample_job(sample_letter_template, notification_count=1, job_status='in progress')
    sample_notification(template=job.template, job=job, status='created')
    result, errors = can_letter_job_be_cancelled(job)
    assert not result
    assert errors == 'We are still processing these letters, please try again in a minute.'


@freeze_time('2019-06-13 13:00')
def test_can_letter_job_be_cancelled_returns_false_and_error_message_if_notifications_not_in_db_yet(
    sample_letter_template,
    sample_notification,
    sample_job,
):
    job = sample_job(sample_letter_template, notification_count=2, job_status='finished')
    sample_notification(template=job.template, job=job, status='created')
    result, errors = can_letter_job_be_cancelled(job)
    assert not result
    assert errors == 'We are still processing these letters, please try again in a minute.'

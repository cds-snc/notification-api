import pytest
from app.dao.fact_notification_status_dao import (
    update_fact_notification_status,
    fetch_monthly_notification_statuses_per_service,
    fetch_notification_status_for_day,
    fetch_notification_status_for_service_by_month,
    fetch_notification_status_for_service_for_day,
    fetch_notification_status_for_service_for_today_and_7_previous_days,
    fetch_notification_status_totals_for_all_services,
    fetch_notification_statuses_for_job,
    fetch_stats_for_all_services_by_date_range,
    fetch_monthly_template_usage_for_service,
    get_total_sent_notifications_for_day_and_type,
    get_total_notifications_sent_for_api_key,
    get_last_send_for_api_key,
    get_api_key_ranked_by_notifications_created,
    fetch_template_usage_for_service_with_given_template,
    fetch_notification_statuses_per_service_and_template_for_date,
    fetch_delivered_notification_stats_by_month,
)
from app.models import (
    FactNotificationStatus,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    KEY_TYPE_TEAM,
    EMAIL_TYPE,
    SMS_TYPE,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
)
from datetime import timedelta, datetime, date
from freezegun import freeze_time
from notifications_utils.timezones import convert_utc_to_local_timezone
from uuid import UUID, uuid4
from unittest import mock


@pytest.mark.serial
def test_update_fact_notification_status(
    notify_db_session, sample_service, sample_template, sample_notification, sample_notification_history
):
    local_now = convert_utc_to_local_timezone(datetime.utcnow())
    first_service = sample_service()
    first_template = sample_template(service=first_service)
    second_service = sample_service()
    second_template = sample_template(service=second_service, template_type=EMAIL_TYPE)
    third_service = sample_service()
    third_template = sample_template(service=third_service, template_type=LETTER_TYPE)

    sample_notification(template=first_template, status='delivered')
    sample_notification(template=first_template, created_at=local_now - timedelta(days=1))
    # simulate a service with data retention - data has been moved to history and does not exist in notifications
    sample_notification_history(template=second_template, status='temporary-failure')
    sample_notification_history(template=second_template, created_at=local_now - timedelta(days=1))
    sample_notification(template=third_template, status='created')
    sample_notification(template=third_template, created_at=local_now - timedelta(days=1))

    process_day = local_now
    data = fetch_notification_status_for_day(process_day=process_day)
    update_fact_notification_status(data=data, process_day=process_day.date())

    new_fact_data = FactNotificationStatus.query.order_by(
        FactNotificationStatus.bst_date, FactNotificationStatus.notification_type
    ).all()

    try:
        assert len(new_fact_data) == 3
        assert new_fact_data[0].bst_date == process_day.date()
        assert new_fact_data[0].template_id == second_template.id
        assert new_fact_data[0].service_id == second_service.id
        assert new_fact_data[0].job_id == UUID('00000000-0000-0000-0000-000000000000')
        assert new_fact_data[0].notification_type == EMAIL_TYPE
        assert new_fact_data[0].notification_status == 'temporary-failure'
        assert new_fact_data[0].notification_count == 1

        assert new_fact_data[1].bst_date == process_day.date()
        assert new_fact_data[1].template_id == third_template.id
        assert new_fact_data[1].service_id == third_service.id
        assert new_fact_data[1].job_id == UUID('00000000-0000-0000-0000-000000000000')
        assert new_fact_data[1].notification_type == LETTER_TYPE
        assert new_fact_data[1].notification_status == 'created'
        assert new_fact_data[1].notification_count == 1

        assert new_fact_data[2].bst_date == process_day.date()
        assert new_fact_data[2].template_id == first_template.id
        assert new_fact_data[2].service_id == first_service.id
        assert new_fact_data[2].job_id == UUID('00000000-0000-0000-0000-000000000000')
        assert new_fact_data[2].notification_type == SMS_TYPE
        assert new_fact_data[2].notification_status == 'delivered'
        assert new_fact_data[2].notification_count == 1
    finally:
        for ft_notification_status in new_fact_data:
            notify_db_session.session.delete(ft_notification_status)
        notify_db_session.session.commit()


@pytest.mark.serial
def test_update_fact_notification_status_updates_row(
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
):
    first_service = sample_service()
    first_template = sample_template(service=first_service)
    sample_notification(template=first_template, status='delivered')

    process_day = convert_utc_to_local_timezone(datetime.utcnow())
    data = fetch_notification_status_for_day(process_day=process_day)
    update_fact_notification_status(data=data, process_day=process_day.date())

    new_fact_data = FactNotificationStatus.query.order_by(
        FactNotificationStatus.bst_date, FactNotificationStatus.notification_type
    ).all()

    try:
        assert len(new_fact_data) == 1
        assert new_fact_data[0].notification_count == 1
    except AssertionError:
        # Teardown
        for ft_notification_status in new_fact_data:
            notify_db_session.session.delete(ft_notification_status)
        notify_db_session.session.commit()
        raise

    sample_notification(template=first_template, status='delivered')

    data = fetch_notification_status_for_day(process_day=process_day)
    update_fact_notification_status(data=data, process_day=process_day.date())

    updated_fact_data = FactNotificationStatus.query.order_by(
        FactNotificationStatus.bst_date, FactNotificationStatus.notification_type
    ).all()

    try:
        assert len(updated_fact_data) == 1
        assert updated_fact_data[0].notification_count == 2
    finally:
        # Teardown
        for ft_notification_status in updated_fact_data:
            notify_db_session.session.delete(ft_notification_status)
        notify_db_session.session.commit()


def test_fetch_notification_status_for_service_by_month(
    sample_service, sample_template, sample_job, sample_ft_notification_status
):
    service1 = sample_service()
    sms_template1 = sample_template(service=service1)
    email_template1 = sample_template(template_type=EMAIL_TYPE, service=service1)
    job1 = sample_job(sms_template1)
    job1_email = sample_job(email_template1)

    service2 = sample_service()
    sms_template2 = sample_template(service=service2)
    job2 = sample_job(sms_template2)

    sample_ft_notification_status(date(2018, 1, 1), job1, count=4)
    sample_ft_notification_status(date(2018, 1, 2), job1, count=10)
    sample_ft_notification_status(date(2018, 1, 2), job1, notification_status='created', status_reason='foo')
    sample_ft_notification_status(date(2018, 1, 3), job1_email)
    sample_ft_notification_status(date(2018, 2, 2), job1)

    # not included - too early
    sample_ft_notification_status(date(2017, 12, 31), job1)
    # not included - too late
    sample_ft_notification_status(date(2017, 3, 1), job1)
    # not included - wrong service
    sample_ft_notification_status(date(2018, 1, 3), job2)
    # not included - test keys
    sample_ft_notification_status(date(2018, 1, 3), job1, key_type=KEY_TYPE_TEST)

    results = sorted(
        fetch_notification_status_for_service_by_month(date(2018, 1, 1), date(2018, 2, 28), service1.id),
        key=lambda x: (x.month, x.notification_type, x.notification_status),
    )

    assert len(results) == 4

    assert results[0].month.date() == date(2018, 1, 1)
    assert results[0].notification_type == EMAIL_TYPE
    assert results[0].notification_status == 'delivered'
    assert results[0].count == 1

    assert results[1].month.date() == date(2018, 1, 1)
    assert results[1].notification_type == SMS_TYPE
    assert results[1].notification_status == 'created'
    assert results[1].count == 1

    assert results[2].month.date() == date(2018, 1, 1)
    assert results[2].notification_type == SMS_TYPE
    assert results[2].notification_status == 'delivered'
    assert results[2].count == 14

    assert results[3].month.date() == date(2018, 2, 1)
    assert results[3].notification_type == SMS_TYPE
    assert results[3].notification_status == 'delivered'
    assert results[3].count == 1


def test_fetch_notification_status_for_service_for_day(sample_service, sample_template, sample_notification):
    service_1 = sample_service()
    service_2 = sample_service()

    sample_template(service=service_1)
    sample_template(service=service_2)

    # too early
    sample_notification(template=service_1.templates[0], created_at=datetime(2018, 5, 31, 22, 59, 0))

    # included
    sample_notification(template=service_1.templates[0], created_at=datetime(2018, 5, 31, 23, 0, 0))
    sample_notification(template=service_1.templates[0], created_at=datetime(2018, 6, 1, 22, 59, 0))
    sample_notification(
        template=service_1.templates[0], created_at=datetime(2018, 6, 1, 12, 0, 0), key_type=KEY_TYPE_TEAM
    )
    sample_notification(template=service_1.templates[0], created_at=datetime(2018, 6, 1, 12, 0, 0), status='delivered')

    # test key
    sample_notification(
        template=service_1.templates[0], created_at=datetime(2018, 6, 1, 12, 0, 0), key_type=KEY_TYPE_TEST
    )

    # wrong service
    sample_notification(template=service_2.templates[0], created_at=datetime(2018, 6, 1, 12, 0, 0))

    # tomorrow (somehow)
    sample_notification(template=service_1.templates[0], created_at=datetime(2018, 6, 1, 23, 0, 0))

    results = sorted(
        fetch_notification_status_for_service_for_day(datetime(2018, 6, 1), service_1.id),
        key=lambda x: x.notification_status,
    )
    assert len(results) == 2

    assert results[0].month == datetime(2018, 6, 1, 0, 0)
    assert results[0].notification_type == SMS_TYPE
    assert results[0].notification_status == 'created'
    assert results[0].count == 3

    assert results[1].month == datetime(2018, 6, 1, 0, 0)
    assert results[1].notification_type == SMS_TYPE
    assert results[1].notification_status == 'delivered'
    assert results[1].count == 1


@freeze_time('1995-10-31T18:00:00')
def test_fetch_notification_status_for_service_for_today_and_7_previous_days(
    sample_service,
    sample_template,
    sample_job,
    sample_notification,
    sample_ft_notification_status,
):
    service = sample_service()
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    sms_template_2 = sample_template(service=service, template_type=SMS_TYPE)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)
    job_sms = sample_job(sms_template)
    job_email = sample_job(email_template)
    job_letter = sample_job(letter_template)

    sample_ft_notification_status(date(1995, 10, 29), job_sms, count=10)
    sample_ft_notification_status(date(1995, 10, 24), job_sms, count=8)
    sample_ft_notification_status(date(1995, 10, 29), job_sms, notification_status='created')
    sample_ft_notification_status(date(1995, 10, 29), job_email, count=3)
    sample_ft_notification_status(date(1995, 10, 26), job_letter, count=5)

    sample_notification(template=sms_template, created_at=datetime(1995, 10, 31, 11, 0, 0))
    sample_notification(template=sms_template_2, created_at=datetime(1995, 10, 31, 11, 0, 0))
    sample_notification(template=sms_template, created_at=datetime(1995, 10, 31, 12, 0, 0), status='delivered')
    sample_notification(template=email_template, created_at=datetime(1995, 10, 31, 13, 0, 0), status='delivered')

    # too early, shouldn't be included
    sample_notification(template=service.templates[0], created_at=datetime(1995, 10, 30, 12, 0, 0), status='delivered')

    results = sorted(
        fetch_notification_status_for_service_for_today_and_7_previous_days(service.id),
        key=lambda x: (x.notification_type, x.status),
    )

    assert len(results) == 4

    assert results[0].notification_type == EMAIL_TYPE
    assert results[0].status == 'delivered'
    assert results[0].count == 4

    assert results[1].notification_type == LETTER_TYPE
    assert results[1].status == 'delivered'
    assert results[1].count == 5

    assert results[2].notification_type == SMS_TYPE
    assert results[2].status == 'created'
    assert results[2].count == 3

    assert results[3].notification_type == SMS_TYPE
    assert results[3].status == 'delivered'
    assert results[3].count == 11


@freeze_time('1993-10-31T18:00:00')
# This test assumes the local timezone is EST
def test_fetch_notification_status_by_template_for_service_for_today_and_7_previous_days(
    sample_service, sample_template, sample_job, sample_notification, sample_ft_notification_status
):
    service = sample_service()

    # The names of the SMS templates are chosen to guarantee sorted order, which is used below.
    sms_template = sample_template(service=service, template_type=SMS_TYPE, name=f'a {uuid4()}')
    sms_template_2 = sample_template(service=service, template_type=SMS_TYPE, name=f'b {uuid4()}')
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)

    job_sms = sample_job(sms_template)
    job_email = sample_job(email_template)
    job_letter = sample_job(letter_template)

    # create unused email template
    sample_template(service=service, template_type=EMAIL_TYPE)

    sample_ft_notification_status(date(1993, 10, 29), job_sms, count=10)
    sample_ft_notification_status(date(1993, 10, 24), job_sms, count=8)
    sample_ft_notification_status(date(1993, 10, 29), job_sms, notification_status='created')
    sample_ft_notification_status(date(1993, 10, 29), job_email, count=3)
    sample_ft_notification_status(date(1993, 10, 26), job_letter, count=5)

    sample_notification(template=sms_template, created_at=datetime(1993, 10, 31, 11, 0, 0))
    sample_notification(template=sms_template, created_at=datetime(1993, 10, 31, 12, 0, 0), status='delivered')
    sample_notification(template=sms_template_2, created_at=datetime(1993, 10, 31, 12, 0, 0), status='delivered')
    sample_notification(template=email_template, created_at=datetime(1993, 10, 31, 13, 0, 0), status='delivered')

    # too early, shouldn't be included
    sample_notification(template=service.templates[0], created_at=datetime(1993, 10, 30, 12, 0, 0), status='delivered')

    results = fetch_notification_status_for_service_for_today_and_7_previous_days(service.id, by_template=True)

    assert [
        (email_template.name, False, mock.ANY, EMAIL_TYPE, 'delivered', 4),
        (letter_template.name, False, mock.ANY, LETTER_TYPE, 'delivered', 5),
        (sms_template.name, False, mock.ANY, SMS_TYPE, 'created', 2),
        (sms_template.name, False, mock.ANY, SMS_TYPE, 'delivered', 11),
        (sms_template_2.name, False, mock.ANY, SMS_TYPE, 'delivered', 1),
    ] == sorted(results, key=lambda x: (x.notification_type, x.status, x.template_name, x.count))


def test_get_total_notifications_sent_for_api_key(
    notify_db_session,
    sample_api_key,
    sample_service,
    sample_template,
    sample_notification,
):
    service = sample_service()
    api_key = sample_api_key(service)
    template_email = sample_template(service=service, template_type=EMAIL_TYPE)
    template_sms = sample_template(service=service, template_type=SMS_TYPE)
    total_sends = 10

    api_key_stats_1 = get_total_notifications_sent_for_api_key(str(api_key.id))
    assert api_key_stats_1 == []

    for _ in range(total_sends):
        sample_notification(template=template_email, api_key=api_key)

    api_key_stats_2 = get_total_notifications_sent_for_api_key(str(api_key.id))
    assert api_key_stats_2 == [
        (EMAIL_TYPE, total_sends),
    ]

    for _ in range(total_sends):
        sample_notification(template=template_sms, api_key=api_key)

    api_key_stats_3 = get_total_notifications_sent_for_api_key(str(api_key.id))

    assert set(api_key_stats_3) == set([(EMAIL_TYPE, total_sends), (SMS_TYPE, total_sends)])


def test_get_last_send_for_api_key(sample_api_key, sample_service, sample_template, sample_notification):
    service = sample_service()
    api_key = sample_api_key(service)
    template_email = sample_template(service=service, template_type=EMAIL_TYPE)
    total_sends = 10

    last_send = get_last_send_for_api_key(str(api_key.id))
    assert last_send == []

    for _ in range(total_sends):
        sample_notification(template=template_email, api_key=api_key)

    # the following lines test that a send has occurred within the last second
    last_send = get_last_send_for_api_key(str(api_key.id))[0][0]
    now = datetime.utcnow()
    time_delta = now - last_send
    assert abs(time_delta.total_seconds()) < 1


@pytest.mark.serial
def test_get_api_key_ranked_by_notifications_created(
    sample_api_key,
    sample_service,
    sample_template,
    sample_notification,
):
    service = sample_service()
    api_key_1 = sample_api_key(service, key_type=KEY_TYPE_NORMAL, key_name='Key 1')
    api_key_2 = sample_api_key(service, key_type=KEY_TYPE_NORMAL, key_name='Key 2')

    template_email = sample_template(service=service, template_type=EMAIL_TYPE)
    template_sms = sample_template(service=service, template_type=SMS_TYPE)
    email_sends = 1
    sms_sends = 10

    for x in range(email_sends):
        sample_notification(template=template_email, api_key=api_key_1)

    for x in range(sms_sends):
        sample_notification(template=template_sms, api_key=api_key_1)
        sample_notification(template=template_sms, api_key=api_key_2)

    api_keys_ranked = get_api_key_ranked_by_notifications_created(2)

    assert len(api_keys_ranked) == 2

    first_place = api_keys_ranked[0]
    second_place = api_keys_ranked[1]

    # check there are 9 fields/columns returned
    assert len(first_place) == 9
    assert len(second_place) == 9

    assert first_place[0] == api_key_1.name
    assert first_place[2] == service.name
    assert int(first_place[6]) == email_sends
    assert int(first_place[7]) == sms_sends
    assert int(first_place[8]) == sms_sends + email_sends

    assert second_place[0] == api_key_2.name
    assert second_place[2] == service.name
    assert int(second_place[6]) == 0
    assert int(second_place[7]) == sms_sends
    assert int(second_place[8]) == sms_sends


@pytest.mark.serial
@pytest.mark.parametrize(
    'start_date, end_date, expected_email, expected_letters, expected_sms, expected_created_sms',
    [
        (29, 30, 3, 10, 10, 1),  # not including today
        (29, 31, 4, 10, 11, 2),  # today included
        (26, 31, 4, 15, 11, 2),
    ],
)
@freeze_time('2018-10-31 14:00')
def test_fetch_notification_status_totals_for_all_services(
    sample_service,
    sample_template,
    sample_job,
    sample_notification,
    sample_ft_notification_status,
    start_date,
    end_date,
    expected_email,
    expected_letters,
    expected_sms,
    expected_created_sms,
):
    year = date.today().year
    set_up_data(
        sample_service,
        sample_template,
        sample_job,
        sample_notification,
        sample_ft_notification_status,
        year,
    )
    results = sorted(
        fetch_notification_status_totals_for_all_services(
            start_date=date(year, 10, start_date), end_date=date(year, 10, end_date)
        ),
        key=lambda x: (x.notification_type, x.status),
    )

    assert len(results) == 4

    assert results[0].notification_type == EMAIL_TYPE
    assert results[0].status == 'delivered'
    assert results[0].count == expected_email

    assert results[1].notification_type == LETTER_TYPE
    assert results[1].status == 'delivered'
    assert results[1].count == expected_letters

    assert results[2].notification_type == SMS_TYPE
    assert results[2].status == 'created'
    assert results[2].count == expected_created_sms

    assert results[3].notification_type == SMS_TYPE
    assert results[3].status == 'delivered'
    assert results[3].count == expected_sms


@pytest.mark.serial
@freeze_time('2018-04-21 14:00')
def test_fetch_notification_status_totals_for_all_services_works_in_bst(
    sample_service,
    sample_template,
    sample_notification,
):
    service_1 = sample_service()
    sms_template = sample_template(service=service_1, template_type=SMS_TYPE)
    email_template = sample_template(service=service_1, template_type=EMAIL_TYPE)

    sample_notification(template=sms_template, created_at=datetime(2018, 4, 20, 12, 0, 0), status='delivered')
    sample_notification(template=sms_template, created_at=datetime(2018, 4, 21, 11, 0, 0), status='created')
    sample_notification(template=sms_template, created_at=datetime(2018, 4, 21, 12, 0, 0), status='delivered')
    sample_notification(template=email_template, created_at=datetime(2018, 4, 21, 13, 0, 0), status='delivered')
    sample_notification(template=email_template, created_at=datetime(2018, 4, 21, 14, 0, 0), status='delivered')

    results = sorted(
        fetch_notification_status_totals_for_all_services(start_date=date(2018, 4, 21), end_date=date(2018, 4, 21)),
        key=lambda x: (x.notification_type, x.status),
    )

    assert len(results) == 3

    assert results[0].notification_type == EMAIL_TYPE
    assert results[0].status == 'delivered'
    assert results[0].count == 2

    assert results[1].notification_type == SMS_TYPE
    assert results[1].status == 'created'
    assert results[1].count == 1

    assert results[2].notification_type == SMS_TYPE
    assert results[2].status == 'delivered'
    assert results[2].count == 1


def set_up_data(
    sample_service,
    sample_template,
    sample_job,
    sample_notification,
    sample_ft_notification_status,
    year=2018,
):
    # Giving the services and templates names is useful for sorting query results downstream.
    service_1 = sample_service(service_name=f'service 1 {uuid4()}')
    service_2 = sample_service(service_name=f'service 2 {uuid4()}')
    sms_template = sample_template(service=service_1, template_type=SMS_TYPE, name=f'sms {uuid4()}')
    email_template = sample_template(service=service_1, template_type=EMAIL_TYPE, name=f'email {uuid4()}')
    letter_template = sample_template(service=service_1, template_type=LETTER_TYPE, name=f'letter {uuid4()}')

    job_sms = sample_job(sms_template)
    job_email = sample_job(email_template)
    job_letter = sample_job(letter_template)

    letter_template2 = sample_template(service=service_2, template_type=LETTER_TYPE)
    job2_letter = sample_job(letter_template2)

    sample_ft_notification_status(date(year, 10, 24), job_sms, count=8)
    sample_ft_notification_status(date(year, 10, 26), job_letter, count=5)
    sample_ft_notification_status(date(year, 10, 29), job_sms, count=10)
    sample_ft_notification_status(date(year, 10, 29), job_sms, notification_status='created')
    sample_ft_notification_status(date(year, 10, 29), job_email, count=3)
    sample_ft_notification_status(date(year, 10, 29), job2_letter, count=10)

    sample_notification(
        template=service_1.templates[0], created_at=datetime(year, 10, 30, 12, 0, 0), status='delivered'
    )
    sample_notification(template=sms_template, created_at=datetime(year, 10, 31, 11, 0, 0))
    sample_notification(template=sms_template, created_at=datetime(year, 10, 31, 12, 0, 0), status='delivered')
    sample_notification(template=email_template, created_at=datetime(year, 10, 31, 13, 0, 0), status='delivered')
    return service_1, service_2


def test_fetch_notification_statuses_for_job(sample_template, sample_job, sample_ft_notification_status):
    template = sample_template()
    j1 = sample_job(template)
    j2 = sample_job(template)

    sample_ft_notification_status(date(2018, 10, 1), job=j1, notification_status='created', count=1)
    sample_ft_notification_status(date(2018, 10, 1), job=j1, notification_status='delivered', count=2)
    sample_ft_notification_status(date(2018, 10, 2), job=j1, notification_status='created', count=4)
    sample_ft_notification_status(date(2018, 10, 1), job=j2, notification_status='created', count=8)

    assert {x.status: x.count for x in fetch_notification_statuses_for_job(j1.id)} == {'created': 5, 'delivered': 2}


@pytest.mark.serial
@freeze_time('2011-10-31 14:00')
def test_fetch_stats_for_all_services_by_date_range(
    sample_service,
    sample_template,
    sample_job,
    sample_notification,
    sample_ft_notification_status,
):
    service_1, service_2 = set_up_data(
        sample_service,
        sample_template,
        sample_job,
        sample_notification,
        sample_ft_notification_status,
        date.today().year,
    )

    results = sorted(
        fetch_stats_for_all_services_by_date_range(start_date=date(2011, 10, 29), end_date=date(2011, 10, 31)),
        key=lambda x: (x.created_at, x.name),
    )
    assert len(results) == 5

    assert results[0].service_id == service_1.id
    assert results[0].notification_type == EMAIL_TYPE
    assert results[0].status == 'delivered'
    assert results[0].count == 4

    assert results[1].service_id == service_1.id
    assert results[1].notification_type == SMS_TYPE
    assert results[1].status == 'created'
    assert results[1].count == 2

    assert results[2].service_id == service_1.id
    assert results[2].notification_type == SMS_TYPE
    assert results[2].status == 'delivered'
    assert results[2].count == 11

    assert results[3].service_id == service_2.id
    assert results[3].notification_type == LETTER_TYPE
    assert results[3].status == 'delivered'
    assert results[3].count == 10

    assert results[4].service_id == service_2.id
    assert results[4].notification_type is None
    assert results[4].status is None
    assert results[4].count is None


@freeze_time('2018-03-30 14:00')
def test_fetch_monthly_template_usage_for_service(
    sample_service,
    sample_template,
    sample_notification,
    sample_job,
    sample_ft_notification_status,
):
    service = sample_service()

    # The names of the templates are chosen to guarantee sorted order, which is used below.
    template_one = sample_template(service=service, template_type=SMS_TYPE, name=f'a {uuid4()}')
    template_two = sample_template(service=service, template_type=EMAIL_TYPE, name=f'b {uuid4()}')
    template_three = sample_template(service=service, template_type=LETTER_TYPE, name=f'c {uuid4()}')

    job_one = sample_job(template_one)
    job_two = sample_job(template_two)
    job_three = sample_job(template_three)

    sample_ft_notification_status(utc_date=date(2017, 12, 10), job=job_two, count=3)
    sample_ft_notification_status(utc_date=date(2017, 12, 10), job=job_one, count=6)
    sample_ft_notification_status(utc_date=date(2018, 1, 1), job=job_one, count=4)
    sample_ft_notification_status(utc_date=date(2018, 3, 1), job=job_three, count=5)

    sample_notification(template=template_three, created_at=datetime.utcnow() - timedelta(days=1))
    sample_notification(template=template_three, created_at=datetime.utcnow())
    results = fetch_monthly_template_usage_for_service(datetime(2017, 4, 1), datetime(2018, 3, 31), service.id)

    assert len(results) == 4

    assert results[0].template_id == template_one.id
    assert results[0].name == template_one.name
    assert results[0].is_precompiled_letter is False
    assert results[0].template_type == template_one.template_type
    assert results[0].month == 12
    assert results[0].year == 2017
    assert results[0].count == 6
    assert results[1].template_id == template_two.id
    assert results[1].name == template_two.name
    assert results[1].is_precompiled_letter is False
    assert results[1].template_type == template_two.template_type
    assert results[1].month == 12
    assert results[1].year == 2017
    assert results[1].count == 3

    assert results[2].template_id == template_one.id
    assert results[2].name == template_one.name
    assert results[2].is_precompiled_letter is False
    assert results[2].template_type == template_one.template_type
    assert results[2].month == 1
    assert results[2].year == 2018
    assert results[2].count == 4

    assert results[3].template_id == template_three.id
    assert results[3].name == template_three.name
    assert results[3].is_precompiled_letter is False
    assert results[3].template_type == template_three.template_type
    assert results[3].month == 3
    assert results[3].year == 2018
    assert results[3].count == 6


@pytest.mark.serial
@freeze_time('2021-01-01 14:00')
def test_fetch_delivered_notification_stats_by_month(
    sample_service,
    sample_template,
    sample_job,
    sample_ft_notification_status,
):
    service = sample_service()

    # The names of the templates are chosen to guarantee sorted order, which is used below.
    sms_template = sample_template(service=service, template_type=SMS_TYPE, name=f'a {uuid4()}')
    email_template = sample_template(service=service, template_type=EMAIL_TYPE, name=f'b {uuid4()}')

    job_sms = sample_job(sms_template)
    job_email = sample_job(email_template)

    # Not counted: before GC Notify started
    sample_ft_notification_status(utc_date=date(2020, 10, 10), job=job_email, count=3)

    sample_ft_notification_status(utc_date=date(2020, 12, 10), job=job_email, count=3)

    sample_ft_notification_status(
        utc_date=date(2021, 12, 5),
        job=job_sms,
        notification_status=NOTIFICATION_DELIVERED,
        count=6,
    )

    sample_ft_notification_status(
        utc_date=date(2021, 1, 1), job=job_sms, notification_status=NOTIFICATION_SENT, status_reason='foo', count=4
    )

    # Not counted: failed notifications
    sample_ft_notification_status(
        utc_date=date(2021, 1, 1),
        job=job_sms,
        notification_status=NOTIFICATION_FAILED,
        count=10,
    )

    sample_ft_notification_status(utc_date=date(2021, 3, 1), job=job_email, count=5)

    results = fetch_delivered_notification_stats_by_month()
    assert len(results) == 5
    assert results[2].count == 4


def test_fetch_delivered_notification_stats_by_month_empty(client):
    assert fetch_delivered_notification_stats_by_month() == []


@pytest.mark.serial
@freeze_time('2018-03-30 14:00')
def test_fetch_monthly_template_usage_for_service_does_join_to_notifications_if_today_is_not_in_date_range(
    sample_service,
    sample_template,
    sample_notification,
    sample_job,
    sample_ft_notification_status,
):
    service = sample_service()

    # The names of the templates are chosen to guarantee sorted order, which is used below.
    template_one = sample_template(service=service, template_type=SMS_TYPE, name=f'a {uuid4()}')
    template_two = sample_template(service=service, template_type=EMAIL_TYPE, name=f'b {uuid4()}')

    job_one = sample_job(template_one)
    job_two = sample_job(template_two)

    sample_ft_notification_status(utc_date=date(2018, 2, 1), job=job_two, count=15)
    sample_ft_notification_status(utc_date=date(2018, 2, 2), job=job_one, count=20)
    sample_ft_notification_status(utc_date=date(2018, 3, 1), job=job_one, count=3)

    sample_notification(template=template_one, created_at=datetime.utcnow())

    results = fetch_monthly_template_usage_for_service(
        datetime(2018, 1, 1), datetime(2018, 2, 20), template_one.service_id
    )

    assert len(results) == 2

    assert results[0].template_id == template_one.id
    assert results[0].name == template_one.name
    assert results[0].is_precompiled_letter == template_one.is_precompiled_letter
    assert results[0].template_type == template_one.template_type
    assert results[0].month == 2
    assert results[0].year == 2018
    assert results[0].count == 20
    assert results[1].template_id == template_two.id
    assert results[1].name == template_two.name
    assert results[1].is_precompiled_letter == template_two.is_precompiled_letter
    assert results[1].template_type == template_two.template_type
    assert results[1].month == 2
    assert results[1].year == 2018
    assert results[1].count == 15


@freeze_time('2018-03-30 14:00')
def test_fetch_monthly_template_usage_for_service_does_not_include_cancelled_status(
    sample_template,
    sample_notification,
    sample_job,
    sample_ft_notification_status,
):
    template = sample_template()
    job = sample_job(template)

    sample_ft_notification_status(utc_date=date(2018, 3, 1), job=job, notification_status='cancelled', count=15)
    sample_notification(template=template, created_at=datetime.utcnow(), status='cancelled')
    sample_notification(template=template, created_at=datetime.utcnow(), status='cancelled', status_reason='foo')

    results = fetch_monthly_template_usage_for_service(datetime(2018, 1, 1), datetime(2018, 3, 31), template.service_id)

    assert len(results) == 0


@freeze_time('2018-03-30 14:00')
def test_fetch_monthly_template_usage_for_service_does_not_include_test_notifications(
    sample_template,
    sample_notification,
    sample_job,
    sample_ft_notification_status,
):
    template = sample_template()
    job = sample_job(template)

    sample_ft_notification_status(
        utc_date=date(2018, 3, 1), job=job, notification_status='delivered', key_type='test', count=15
    )

    sample_notification(
        template=template,
        created_at=datetime.utcnow(),
        status='delivered',
        key_type='test',
    )

    results = fetch_monthly_template_usage_for_service(datetime(2018, 1, 1), datetime(2018, 3, 31), template.service_id)

    assert len(results) == 0


@pytest.mark.serial
@pytest.mark.parametrize(
    'notification_type, count',
    [
        (SMS_TYPE, 3),
        (EMAIL_TYPE, 5),
    ],
)
def test_get_total_sent_notifications_for_day_and_type_returns_right_notification_type(
    notification_type,
    count,
    sample_template,
    sample_job,
    sample_ft_notification_status,
):
    sms_template = sample_template()
    job_sms = sample_job(sms_template)
    sample_ft_notification_status(utc_date='2019-03-27', job=job_sms, count=3)

    email_template = sample_template(template_type=EMAIL_TYPE)
    job_email = sample_job(email_template)
    sample_ft_notification_status(utc_date='2019-03-27', job=job_email, count=5)

    result = get_total_sent_notifications_for_day_and_type(day='2019-03-27', notification_type=notification_type)

    assert result == count


@pytest.mark.parametrize('day', ['2019-01-27', '2019-04-02'])
def test_get_total_sent_notifications_for_day_and_type_returns_total_for_right_day(
    day,
    sample_template,
    sample_job,
    sample_ft_notification_status,
):
    template = sample_template()
    job = sample_job(template)

    date = datetime.strptime(day, '%Y-%m-%d')
    sample_ft_notification_status(utc_date=date - timedelta(days=1), job=job, count=1)
    sample_ft_notification_status(utc_date=date, job=job, count=2)
    sample_ft_notification_status(utc_date=date + timedelta(days=1), job=job, count=3)
    sample_ft_notification_status(
        utc_date=date + timedelta(days=1), job=job, notification_status='foo', status_reason='bar', count=3
    )

    total = get_total_sent_notifications_for_day_and_type(day, template.template_type)

    assert total == 2


def test_get_total_sent_notifications_for_day_and_type_returns_zero_when_no_counts(client):
    total = get_total_sent_notifications_for_day_and_type('1776-03-27', SMS_TYPE)
    assert total == 0


@freeze_time('2019-05-10 14:00')
def test_fetch_notification_statuses_per_service_and_template_for_date(
    sample_service,
    sample_template,
    sample_job,
    sample_ft_notification_status,
):
    service = sample_service()

    # The names of the templates are chosen to guarantee sorted order, which is used below.
    sms_template = sample_template(service=service, name=f'a {uuid4()}')
    email_template = sample_template(service=service, template_type=EMAIL_TYPE, name=f'b {uuid4()}')

    job_sms = sample_job(sms_template)
    job_email = sample_job(email_template)

    sample_ft_notification_status(
        date(2019, 4, 30),
        job=job_email,
        notification_status=NOTIFICATION_PERMANENT_FAILURE,
        status_reason='baz',
        count=4,
    )

    sample_ft_notification_status(
        date(2019, 4, 30), job=job_sms, notification_status=NOTIFICATION_DELIVERED, status_reason='foo', count=2
    )

    sample_ft_notification_status(
        date(2019, 4, 30), job=job_sms, notification_status=NOTIFICATION_TECHNICAL_FAILURE, count=5
    )

    sample_ft_notification_status(
        date(2019, 4, 30), job=job_sms, notification_status=NOTIFICATION_PERMANENT_FAILURE, status_reason='bar', count=5
    )

    results = fetch_notification_statuses_per_service_and_template_for_date(date(2019, 4, 30))
    assert len(results) == 4

    # "service id", "service name", "template id", "template name", "status", "reason", "count", "channel_type"
    assert [
        (service.id, service.name, sms_template.id, sms_template.name, NOTIFICATION_DELIVERED, 'foo', 2, SMS_TYPE),
        (
            service.id,
            service.name,
            sms_template.id,
            sms_template.name,
            NOTIFICATION_PERMANENT_FAILURE,
            'bar',
            5,
            SMS_TYPE,
        ),
        (service.id, service.name, sms_template.id, sms_template.name, NOTIFICATION_TECHNICAL_FAILURE, '', 5, SMS_TYPE),
        (
            service.id,
            service.name,
            email_template.id,
            email_template.name,
            NOTIFICATION_PERMANENT_FAILURE,
            'baz',
            4,
            EMAIL_TYPE,
        ),
    ] == sorted(results, key=lambda x: (x.template_name, x.status, x.status_reason, x.count, x.channel_type))


@freeze_time('2019-05-10 14:00')
def test_fetch_notif_statuses_per_service_and_template_for_date_ignores_research_mode_and_test_key(
    sample_service,
    sample_template,
    sample_job,
    sample_ft_notification_status,
):
    research_mode_service = sample_service(research_mode=True)
    research_mode_template = sample_template(service=research_mode_service, template_type=EMAIL_TYPE)
    job_research = sample_job(research_mode_template)

    sample_ft_notification_status(
        date(2019, 4, 30),
        job=job_research,
        notification_status=NOTIFICATION_PERMANENT_FAILURE,
        status_reason='baz',
        count=4,
    )

    service = sample_service()
    template = sample_template(service=service, template_type=EMAIL_TYPE)
    job = sample_job(template)

    sample_ft_notification_status(
        date(2019, 4, 30),
        job=job,
        notification_status=NOTIFICATION_PERMANENT_FAILURE,
        key_type=KEY_TYPE_TEST,
        status_reason='baz',
        count=4,
    )

    results = fetch_notification_statuses_per_service_and_template_for_date(date(2019, 4, 30))
    assert len(results) == 0


@pytest.mark.serial
@freeze_time('2019-05-10 14:00')
def test_fetch_monthly_notification_statuses_per_service(
    sample_service,
    sample_template,
    sample_job,
    sample_ft_notification_status,
):
    # The names of the services and templates are chosen to guarantee sorted order, which is used below.
    service_one = sample_service(service_name=f'one {uuid4()}')
    service_two = sample_service(service_name=f'two {uuid4()}')

    sms_template = sample_template(service=service_one, template_type=SMS_TYPE, name=f'a {uuid4()}')
    email_template = sample_template(service=service_one, template_type=EMAIL_TYPE, name=f'b {uuid4()}')
    letter_template = sample_template(service=service_one, template_type=LETTER_TYPE, name=f'c {uuid4()}')
    letter_template2 = sample_template(service=service_two, template_type=LETTER_TYPE, name=f'd {uuid4()}')

    job_sms = sample_job(sms_template)
    job_email = sample_job(email_template)
    job_letter = sample_job(letter_template)
    job2_letter = sample_job(letter_template2)

    sample_ft_notification_status(date(2019, 4, 30), job=job_letter, notification_status=NOTIFICATION_DELIVERED)
    sample_ft_notification_status(date(2019, 3, 1), job=job_email, notification_status=NOTIFICATION_SENDING, count=4)
    sample_ft_notification_status(
        date(2019, 3, 2), job=job_email, notification_status=NOTIFICATION_TECHNICAL_FAILURE, count=2
    )
    sample_ft_notification_status(date(2019, 3, 7), job=job_email, notification_status=NOTIFICATION_FAILED, count=1)
    sample_ft_notification_status(
        date(2019, 3, 7),
        job=job2_letter,
        notification_status=NOTIFICATION_PERMANENT_FAILURE,
        status_reason='fleens',
        count=1,
    )
    sample_ft_notification_status(
        date(2019, 3, 10), job=job2_letter, notification_status=NOTIFICATION_PERMANENT_FAILURE, count=1
    )
    sample_ft_notification_status(date(2019, 3, 13), job=job_sms, notification_status=NOTIFICATION_SENT, count=1)
    sample_ft_notification_status(
        date(2019, 4, 1), job=job2_letter, notification_status=NOTIFICATION_TEMPORARY_FAILURE, count=10
    )
    sample_ft_notification_status(date(2019, 3, 31), job=job_letter, notification_status=NOTIFICATION_DELIVERED)

    results = sorted(
        fetch_monthly_notification_statuses_per_service(date(2019, 3, 1), date(2019, 4, 30)),
        key=lambda x: (x.date_created, x.service_name, x.notification_type, x.count),
    )
    assert len(results) == 6

    # column order: date, service_id, service_name, notifaction_type, count_sending, count_delivered,
    # count_technical_failure, count_temporary_failure, count_permanent_failure, count_sent
    assert [x for x in results[0]] == [date(2019, 3, 1), service_one.id, service_one.name, EMAIL_TYPE, 4, 0, 3, 0, 0, 0]
    assert [x for x in results[1]] == [
        date(2019, 3, 1),
        service_one.id,
        service_one.name,
        LETTER_TYPE,
        0,
        1,
        0,
        0,
        0,
        0,
    ]
    assert [x for x in results[2]] == [date(2019, 3, 1), service_one.id, service_one.name, SMS_TYPE, 0, 0, 0, 0, 0, 1]
    assert [x for x in results[3]] == [
        date(2019, 3, 1),
        service_two.id,
        service_two.name,
        LETTER_TYPE,
        0,
        0,
        0,
        0,
        2,
        0,
    ]
    assert [x for x in results[4]] == [
        date(2019, 4, 1),
        service_one.id,
        service_one.name,
        LETTER_TYPE,
        0,
        1,
        0,
        0,
        0,
        0,
    ]
    assert [x for x in results[5]] == [
        date(2019, 4, 1),
        service_two.id,
        service_two.name,
        LETTER_TYPE,
        0,
        0,
        0,
        10,
        0,
        0,
    ]


@pytest.mark.serial
@freeze_time('2019-04-10 14:00')
def test_fetch_monthly_notification_statuses_per_service_for_rows_that_should_be_excluded(
    sample_service,
    sample_template,
    sample_job,
    sample_ft_notification_status,
):
    valid_service = sample_service()
    template_valid_service = sample_template(service=valid_service)
    job_valid_service = sample_job(template_valid_service)

    inactive_service = sample_service(active=False)
    template_inactive_service = sample_template(service=inactive_service)
    job_inactive_service = sample_job(template_inactive_service)

    research_mode_service = sample_service(research_mode=True)
    template_research_mode_service = sample_template(service=research_mode_service)
    job_research_mode_service = sample_job(template_research_mode_service)

    restricted_service = sample_service(restricted=True)
    template_restricted_service = sample_template(service=restricted_service)
    job_restricted_service = sample_job(template_restricted_service)

    # notification in 'created' state
    sample_ft_notification_status(date(2019, 3, 15), job=job_valid_service, notification_status=NOTIFICATION_CREATED)
    # notification created by inactive service
    sample_ft_notification_status(date(2019, 3, 15), job=job_inactive_service)
    # notification created with test key
    sample_ft_notification_status(date(2019, 3, 12), job=job_valid_service, key_type=KEY_TYPE_TEST)
    # notification created by research mode service
    sample_ft_notification_status(date(2019, 3, 2), job=job_research_mode_service)
    # notification created by trial mode service
    sample_ft_notification_status(date(2019, 3, 19), job=job_restricted_service)
    # notifications outside date range
    sample_ft_notification_status(date(2019, 2, 28), job=job_valid_service)
    sample_ft_notification_status(date(2019, 4, 1), job=job_valid_service)

    results = fetch_monthly_notification_statuses_per_service(date(2019, 3, 1), date(2019, 3, 31))
    assert len(results) == 0


class TestFetchTemplateUsageForServiceWithGivenTemplate:
    @freeze_time('2021-10-18 14:00')
    def test_fetch_template_usage_for_service_with_given_template_gets_everything_if_dates_not_specified(
        self,
        sample_service,
        sample_template,
        sample_job,
        sample_ft_notification_status,
    ):
        valid_service = sample_service()
        valid_template = sample_template(service=valid_service)
        job = sample_job(valid_template)

        sample_ft_notification_status(date(2019, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 10, 18), job=job)

        results = fetch_template_usage_for_service_with_given_template(valid_service.id, valid_template.id)
        assert results[0][1] == 3

    @freeze_time('2021-10-18 14:00')
    def test_fetch_template_usage_for_service_with_given_template_gets_notifications_before_end_date(
        self,
        sample_service,
        sample_template,
        sample_job,
        sample_ft_notification_status,
    ):
        valid_service = sample_service()
        valid_template = sample_template(service=valid_service)
        job = sample_job(valid_template)

        sample_ft_notification_status(date(2019, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 10, 18), job=job)

        results = fetch_template_usage_for_service_with_given_template(
            valid_service.id, valid_template.id, end_date=date(2021, 10, 17)
        )
        assert results[0][1] == 2

    @freeze_time('2021-10-18 14:00')
    def test_fetch_template_usage_for_service_with_given_template_gets_notifications_after_start_date(
        self,
        sample_service,
        sample_template,
        sample_job,
        sample_ft_notification_status,
    ):
        valid_service = sample_service()
        valid_template = sample_template(service=valid_service)
        job = sample_job(valid_template)

        sample_ft_notification_status(date(2019, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 10, 18), job=job)

        results = fetch_template_usage_for_service_with_given_template(
            valid_service.id, valid_template.id, start_date=date(2020, 1, 1)
        )
        assert results[0][1] == 2

    @freeze_time('2021-10-18 14:00')
    def test_fetch_template_usage_for_service_with_given_template_gets_notifications_between_dates(
        self,
        sample_service,
        sample_template,
        sample_job,
        sample_ft_notification_status,
    ):
        valid_service = sample_service()
        valid_template = sample_template(service=valid_service)
        job = sample_job(valid_template)

        sample_ft_notification_status(date(2019, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 10, 18), job=job)

        results = fetch_template_usage_for_service_with_given_template(
            valid_service.id, valid_template.id, start_date=date(2019, 3, 16), end_date=date(2021, 10, 17)
        )
        assert results[0][1] == 1

    @freeze_time('2021-10-18 14:00')
    def test_fetch_template_usage_for_service_with_given_template_gets_no_notifications(
        self,
        sample_service,
        sample_template,
        sample_job,
        sample_ft_notification_status,
    ):
        valid_service = sample_service()
        valid_template = sample_template(service=valid_service)
        job = sample_job(valid_template)

        sample_ft_notification_status(date(2019, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 10, 18), job=job)

        results = fetch_template_usage_for_service_with_given_template(
            valid_service.id, valid_template.id, start_date=date(2018, 3, 16), end_date=date(2018, 10, 17)
        )
        assert not results

    @freeze_time('2021-10-18 14:00')
    def test_fetch_template_usage_for_service_with_given_template_gets_no_notifications_if_template_id_incorrect(
        self,
        sample_service,
        sample_template,
        sample_job,
        sample_ft_notification_status,
    ):
        valid_service = sample_service()
        valid_template = sample_template(service=valid_service)
        job = sample_job(valid_template)

        sample_ft_notification_status(date(2019, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 10, 18), job=job)

        results = fetch_template_usage_for_service_with_given_template(valid_service.id, uuid4())

        assert not results

    @freeze_time('2021-10-18 14:00')
    def test_fetch_template_usage_for_service_with_given_template_gets_no_notifications_if_service_id_incorrect(
        self,
        sample_service,
        sample_template,
        sample_job,
        sample_ft_notification_status,
    ):
        valid_service = sample_service()
        valid_template = sample_template(service=valid_service)
        job = sample_job(valid_template)

        sample_ft_notification_status(date(2019, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 3, 15), job=job)
        sample_ft_notification_status(date(2021, 10, 18), job=job)

        results = fetch_template_usage_for_service_with_given_template(uuid4(), valid_template.id)

        assert not results

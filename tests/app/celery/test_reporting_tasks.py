from datetime import datetime, timedelta, date
from decimal import Decimal
import uuid

from flask import current_app
from freezegun import freeze_time
from notifications_utils.timezones import convert_utc_to_local_timezone
import pytest
from sqlalchemy import delete, func, select

from app.celery.reporting_tasks import (
    create_nightly_billing,
    create_nightly_notification_status,
    create_nightly_billing_for_day,
    create_nightly_notification_status_for_day,
    generate_daily_notification_status_csv_report,
    generate_nightly_billing_csv_report,
)
from app.constants import EMAIL_TYPE, LETTER_TYPE, SMS_TYPE
from app.dao.fact_billing_dao import get_rate
from app.feature_flags import FeatureFlag
from app.models import FactBilling, FactNotificationStatus
from tests.app.factories.feature_flag import mock_feature_flag


def mocker_get_rate(
    non_letter_rates,
    letter_rates,
    notification_type,
    bst_date,
    crown=None,
    rate_multiplier=None,
    post_class='second',
):
    if notification_type == LETTER_TYPE:
        return Decimal(2.1)
    elif notification_type == SMS_TYPE:
        return Decimal(1.33)
    elif notification_type == EMAIL_TYPE:
        return Decimal(0)


@freeze_time('2019-08-01T04:30:00')
@pytest.mark.parametrize(
    'day_start, expected_kwargs',
    [
        (None, ['2019-07-31', '2019-07-30', '2019-07-29', '2019-07-28']),
        ('2019-07-21', ['2019-07-21', '2019-07-20', '2019-07-19', '2019-07-18']),
    ],
)
def test_create_nightly_billing_triggers_tasks_for_days(
    notify_api,
    mocker,
    day_start,
    expected_kwargs,
):
    mock_billing_for_day = mocker.patch('app.celery.reporting_tasks.create_nightly_billing_for_day')
    mock_billing_csv_report = mocker.patch('app.celery.reporting_tasks.generate_nightly_billing_csv_report')
    create_nightly_billing(day_start)

    assert mock_billing_for_day.si.call_count == 4
    assert mock_billing_csv_report.si.call_count == 4

    for i in range(4):
        assert mock_billing_for_day.si.call_args_list[i][0][0] == expected_kwargs[i]


@freeze_time('2019-08-01T04:30:00')
@pytest.mark.parametrize(
    'day_start, expected_kwargs',
    [
        (None, ['2019-07-31', '2019-07-30', '2019-07-29', '2019-07-28']),
        ('2019-07-21', ['2019-07-21', '2019-07-20', '2019-07-19', '2019-07-18']),
    ],
)
def test_create_nightly_notification_status_triggers_tasks_for_days(
    notify_api,
    mocker,
    day_start,
    expected_kwargs,
):
    mock_celery = mocker.patch('app.celery.reporting_tasks.create_nightly_notification_status_for_day')
    create_nightly_notification_status(day_start)

    assert mock_celery.si.call_count == 4

    for i in range(4):
        assert mock_celery.si.call_args_list[i][0][0] == expected_kwargs[i]


@freeze_time('2019-08-01T04:30:00')
@pytest.mark.parametrize(
    'day_start, expected_kwargs',
    [
        (None, ['2019-07-31', '2019-07-30', '2019-07-29', '2019-07-28']),
        ('2019-07-21', ['2019-07-21', '2019-07-20', '2019-07-19', '2019-07-18']),
    ],
)
def test_create_nightly_notification_status_triggers_tasks_for_days_including_csv_generation_when_feature_flag_on(
    notify_api,
    mocker,
    day_start,
    expected_kwargs,
):
    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    mock_celery = mocker.patch('app.celery.reporting_tasks.create_nightly_notification_status_for_day')
    create_nightly_notification_status(day_start)

    assert mock_celery.si.call_count == 4
    for i in range(4):
        assert mock_celery.si.call_args_list[i][0][0] == expected_kwargs[i]


@pytest.mark.parametrize(
    'second_rate, records_num, billable_units, multiplier',
    [
        (1.0, 1, 2, [1]),
        (2.0, 2, 1, [1, 2]),
    ],
)
def test_create_nightly_billing_for_day_sms_rate_multiplier(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
    sample_provider,
    second_rate,
    records_num,
    billable_units,
    multiplier,
):
    yesterday = convert_utc_to_local_timezone((datetime.now() - timedelta(days=1))).replace(hour=12, minute=00)
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    template = sample_template()
    provider = sample_provider(str(uuid.uuid4()))

    assert template.template_type == SMS_TYPE

    # These are sms notifications (because that matches the template type).
    sample_notification(
        created_at=yesterday,
        template=template,
        status='delivered',
        sent_by=provider.identifier,
        international=False,
        rate_multiplier=1.0,
        billable_units=1,
    )

    sample_notification(
        created_at=yesterday,
        template=template,
        status='delivered',
        sent_by=provider.identifier,
        international=False,
        rate_multiplier=second_rate,
        billable_units=1,
    )

    stmt = select(FactBilling).where(FactBilling.template_id == template.id).order_by('rate_multiplier')
    assert len(notify_db_session.session.scalars(stmt).all()) == 0

    # Celery expects the arguments to be a string or primitive type.
    yesterday_str = datetime.strftime(yesterday, '%Y-%m-%d')
    try:
        create_nightly_billing_for_day(yesterday_str)

        records = notify_db_session.session.scalars(stmt).all()
        assert len(records) == records_num

        for i, record in enumerate(records):
            assert record.bst_date == datetime.date(yesterday)
            assert record.rate == Decimal(1.33)
            assert record.billable_units == billable_units
            assert record.rate_multiplier == multiplier[i]
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_create_nightly_billing_for_day_different_templates(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    yesterday = convert_utc_to_local_timezone((datetime.now() - timedelta(days=1))).replace(hour=12, minute=00)
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    sms_template = sample_template()
    email_template = sample_template(template_type=EMAIL_TYPE)

    sample_notification(
        created_at=yesterday,
        template=sms_template,
        status='delivered',
        sent_by='mmg',
        international=False,
        rate_multiplier=1.0,
        billable_units=1,
    )

    sample_notification(
        created_at=yesterday,
        template=email_template,
        status='delivered',
        sent_by='ses',
        international=False,
        rate_multiplier=0,
        billable_units=0,
    )

    stmt = (
        select(FactBilling)
        .where(FactBilling.template_id.in_((sms_template.id, email_template.id)))
        .order_by('rate_multiplier')
    )
    assert len(notify_db_session.session.scalars(stmt).all()) == 0

    # Celery expects the arguments to be a string or primitive type.
    yesterday_str = datetime.strftime(yesterday, '%Y-%m-%d')

    try:
        create_nightly_billing_for_day(yesterday_str)

        records = notify_db_session.session.scalars(stmt).all()

        assert len(records) == 2
        multiplier = [0, 1]
        billable_units = [0, 1]
        rate = [0, Decimal(1.33)]
        for i, record in enumerate(records):
            assert record.bst_date == datetime.date(yesterday)
            assert record.rate == rate[i]
            assert record.billable_units == billable_units[i]
            assert record.rate_multiplier == multiplier[i]
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id.in_((email_template.id, sms_template.id)))
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_create_nightly_billing_for_day_different_sent_by(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    yesterday = convert_utc_to_local_timezone((datetime.now() - timedelta(days=1))).replace(hour=12, minute=00)
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    template = sample_template()

    # These are sms notifications
    sample_notification(
        created_at=yesterday,
        template=template,
        status='delivered',
        sent_by='mmg',
        international=False,
        rate_multiplier=1.0,
        billable_units=1,
    )

    sample_notification(
        created_at=yesterday,
        template=template,
        status='delivered',
        sent_by='firetext',
        international=False,
        rate_multiplier=1.0,
        billable_units=1,
    )

    stmt = select(func.count()).select_from(FactBilling).where(FactBilling.template_id == template.id)
    assert notify_db_session.session.scalar(stmt) == 0

    # Celery expects the arguments to be a string or primitive type.
    yesterday_str = datetime.strftime(yesterday, '%Y-%m-%d')

    try:
        create_nightly_billing_for_day(yesterday_str)

        stmt = select(FactBilling).where(FactBilling.template_id == template.id).order_by('rate_multiplier')
        records = notify_db_session.session.scalars(stmt).all()

        assert len(records) == 2
        for i, record in enumerate(records):
            assert record.bst_date == datetime.date(yesterday)
            assert record.rate == Decimal(1.33)
            assert record.billable_units == 1
            assert record.rate_multiplier == 1.0
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_create_nightly_billing_for_day_different_letter_postage(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    yesterday = convert_utc_to_local_timezone((datetime.now() - timedelta(days=1))).replace(hour=12, minute=00)
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    template = sample_template(template_type=LETTER_TYPE)

    for i in range(2):
        sample_notification(
            created_at=yesterday,
            template=template,
            status='delivered',
            sent_by='dvla',
            billable_units=2,
            postage='first',
        )
    sample_notification(
        created_at=yesterday,
        template=template,
        status='delivered',
        sent_by='dvla',
        billable_units=2,
        postage='second',
    )

    stmt = select(func.count()).select_from(FactBilling).where(FactBilling.template_id == template.id)
    assert notify_db_session.session.scalar(stmt) == 0

    # Celery expects the arguments to be a string or primitive type.
    yesterday_str = datetime.strftime(yesterday, '%Y-%m-%d')

    try:
        create_nightly_billing_for_day(yesterday_str)

        stmt = select(FactBilling).where(FactBilling.template_id == template.id).order_by('postage')
        records = notify_db_session.session.scalars(stmt).all()

        assert len(records) == 2
        assert records[0].notification_type == LETTER_TYPE
        assert records[0].bst_date == datetime.date(yesterday)
        assert records[0].postage == 'first'
        assert records[0].notifications_sent == 2
        assert records[0].billable_units == 4

        assert records[1].notification_type == LETTER_TYPE
        assert records[1].bst_date == datetime.date(yesterday)
        assert records[1].postage == 'second'
        assert records[1].notifications_sent == 1
        assert records[1].billable_units == 2
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_create_nightly_billing_for_day_letter(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    yesterday = convert_utc_to_local_timezone((datetime.now() - timedelta(days=1))).replace(hour=12, minute=00)
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    template = sample_template(template_type=LETTER_TYPE)

    sample_notification(
        created_at=yesterday,
        template=template,
        status='delivered',
        sent_by='dvla',
        international=False,
        rate_multiplier=2.0,
        billable_units=2,
    )

    stmt = select(FactBilling).where(FactBilling.template_id == template.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 0

    try:
        # Celery expects the arguments to be a string or primitive type.
        yesterday_str = datetime.strftime(yesterday, '%Y-%m-%d')
        create_nightly_billing_for_day(yesterday_str)

        records = notify_db_session.session.scalars(stmt).all()
        assert len(records) == 1
        assert records[0].notification_type == LETTER_TYPE
        assert records[0].bst_date == datetime.date(yesterday)
        assert records[0].rate == Decimal(2.1)
        assert records[0].billable_units == 2
        assert records[0].rate_multiplier == 2.0
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


@freeze_time('1999-12-04 16:00:00.000000')
def test_create_nightly_billing_for_day_null_sent_by_sms(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    yesterday = convert_utc_to_local_timezone((datetime.now() - timedelta(days=1))).replace(hour=12, minute=00)
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    template = sample_template()

    sample_notification(
        created_at=yesterday,
        template=template,
        status='delivered',
        sent_by=None,
        international=False,
        rate_multiplier=1.0,
        billable_units=1,
    )

    stmt = select(FactBilling).where(FactBilling.template_id == template.id)
    try:
        assert len(notify_db_session.session.scalars(stmt).all()) == 0

        # Celery expects the arguments to be a string or primitive type.
        yesterday_str = datetime.strftime(yesterday, '%Y-%m-%d')
        create_nightly_billing_for_day(yesterday_str)

        records = notify_db_session.session.scalars(stmt).all()
        assert len(records) == 1
        assert records[0].bst_date == datetime.date(yesterday)
        assert records[0].rate == Decimal(1.33)
        assert records[0].billable_units == 1
        assert records[0].rate_multiplier == 1
        assert records[0].provider == 'unknown'
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_get_rate_for_letter_latest(sample_letter_rate):
    # letter rates should be passed into the get_rate function as a tuple of start_date, crown, sheet_count,
    # rate and post_class
    new = sample_letter_rate(datetime(2017, 12, 1), crown=True, sheet_count=1, rate=0.33, post_class='second')
    old = sample_letter_rate(datetime(2016, 12, 1), crown=True, sheet_count=1, rate=0.30, post_class='second')
    letter_rates = [new, old]

    rate = get_rate([], letter_rates, LETTER_TYPE, date(2018, 1, 1), True, 1)

    assert rate == Decimal('0.33')


def test_get_rate_for_sms_and_email(
    notify_api,
    sample_rate,
):
    non_letter_rates = [
        sample_rate(datetime(2017, 12, 1), 0.15, SMS_TYPE),
        sample_rate(datetime(2017, 12, 1), 0, EMAIL_TYPE),
    ]

    rate = get_rate(non_letter_rates, [], SMS_TYPE, date(2018, 1, 1))
    assert rate == Decimal(0.15)

    rate = get_rate(non_letter_rates, [], EMAIL_TYPE, date(2018, 1, 1))
    assert rate == Decimal(0)


@freeze_time('1992-03-30T05:00:00')
# summer time starts on 1992-03-25
def test_create_nightly_billing_for_day_use_BST(
    mocker,
    notify_db_session,
    sample_template,
    sample_notification,
):
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    template = sample_template()

    # too late
    sample_notification(
        created_at=datetime(1992, 3, 25, 23, 1),
        template=template,
        status='delivered',
        rate_multiplier=1.0,
        billable_units=1,
    )

    sample_notification(
        created_at=datetime(1992, 3, 25, 22, 59),
        template=template,
        status='delivered',
        rate_multiplier=1.0,
        billable_units=2,
    )

    # too early
    sample_notification(
        created_at=datetime(1992, 3, 24, 23, 59),
        template=template,
        status='delivered',
        rate_multiplier=1.0,
        billable_units=4,
    )

    stmt = select(FactBilling).where(FactBilling.template_id == template.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 0

    try:
        create_nightly_billing_for_day('1992-03-25')

        records = notify_db_session.session.scalars(stmt).all()

        assert len(records) == 1
        assert records[0].bst_date == date(1992, 3, 25)
        assert records[0].billable_units == 3
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


@freeze_time('2018-01-15T010:30:00')
def test_create_nightly_billing_for_day_update_when_record_exists(
    notify_db_session,
    mocker,
    sample_template,
    sample_notification,
):
    mocker.patch('app.dao.fact_billing_dao.get_rate', side_effect=mocker_get_rate)
    template = sample_template()

    sample_notification(
        created_at=datetime.now() - timedelta(days=1),
        template=template,
        status='delivered',
        sent_by=None,
        international=False,
        rate_multiplier=1.0,
        billable_units=1,
    )
    stmt = select(FactBilling).where(FactBilling.template_id == template.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 0

    try:
        create_nightly_billing_for_day('2018-01-14')
        records = notify_db_session.session.scalars(stmt).all()

        assert len(records) == 1
        assert records[0].bst_date == date(2018, 1, 14)
        assert records[0].billable_units == 1
        assert not records[0].updated_at

        sample_notification(
            created_at=datetime.now() - timedelta(days=1),
            template=template,
            status='delivered',
            sent_by=None,
            international=False,
            rate_multiplier=1.0,
            billable_units=1,
        )

        # run again, make sure create_nightly_billing() updates with no error
        create_nightly_billing_for_day('2018-01-14')
        records = notify_db_session.session.scalars(stmt).all()
        assert len(records) == 1
        assert records[0].billable_units == 2
        assert records[0].updated_at
    finally:
        # Teardown
        stmt = delete(FactBilling).where(FactBilling.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


@freeze_time('1994-01-05')
def test_create_nightly_notification_status_for_day(
    notify_db_session, sample_service, sample_template, sample_notification
):
    first_service = sample_service()
    first_template = sample_template(service=first_service)
    second_service = sample_service()
    second_template = sample_template(service=second_service, template_type=EMAIL_TYPE)
    third_service = sample_service()
    third_template = sample_template(service=third_service, template_type=LETTER_TYPE)
    service_ids = (first_service.id, second_service.id, third_service.id)

    sample_notification(template=first_template, status='delivered')
    sample_notification(template=first_template, status='delivered', created_at=datetime(1994, 1, 1, 12, 0))

    sample_notification(template=second_template, status='temporary-failure')
    sample_notification(template=second_template, status='temporary-failure', created_at=datetime(1994, 1, 1, 12, 0))

    sample_notification(template=third_template, status='created')
    sample_notification(template=third_template, status='created', created_at=datetime(1994, 1, 1, 12, 0))

    stmt = select(FactNotificationStatus).where(
        FactNotificationStatus.template_id.in_((first_template.id, second_template.id, third_template.id))
    )

    assert len(notify_db_session.session.scalars(stmt).all()) == 0

    create_nightly_notification_status_for_day('1994-01-01')

    new_data = notify_db_session.session.scalars(stmt).all()

    try:
        assert len(new_data) == 3
        assert new_data[0].bst_date == date(1994, 1, 1)
        assert new_data[1].bst_date == date(1994, 1, 1)
        assert new_data[2].bst_date == date(1994, 1, 1)
    finally:
        # Teardown
        stmt = delete(FactNotificationStatus).where(FactNotificationStatus.service_id.in_(service_ids))
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


# the job runs at 12:30am London time. 04/01 is in BST.
@freeze_time('2019-04-01T5:30')
def test_create_nightly_notification_status_for_day_respects_local_timezone(
    notify_db_session,
    sample_template,
    sample_notification,
):
    template = sample_template()

    sample_notification(template=template, status='delivered', created_at=datetime(2019, 4, 2, 5, 0))  # too new
    sample_notification(template=template, status='created', created_at=datetime(2019, 4, 2, 6, 59))
    sample_notification(template=template, status='created', created_at=datetime(2019, 4, 1, 5, 59))
    sample_notification(template=template, status='delivered', created_at=datetime(2019, 3, 30, 3, 59))  # too old

    create_nightly_notification_status_for_day('2019-04-01')

    stmt = select(FactNotificationStatus).where(FactNotificationStatus.template_id == template.id)
    noti_status = notify_db_session.session.scalars(stmt).all()

    try:
        assert len(noti_status) == 1
        assert noti_status[0].bst_date == date(2019, 4, 1)
        assert noti_status[0].notification_status == 'created'
    finally:
        # Teardown
        stmt = delete(FactNotificationStatus).where(FactNotificationStatus.template_id == template.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_generate_daily_notification_status_csv_report(notify_api, mocker):
    service_id = uuid.uuid4()
    template_id = uuid.uuid4()
    mock_transit_data = [
        (service_id, 'foo', template_id, 'bar', 'delivered', '', 1, EMAIL_TYPE),
        (service_id, 'foo', template_id, 'bar', 'delivered', 'baz', 1, SMS_TYPE),
    ]
    mocker.patch(
        'app.celery.reporting_tasks.fetch_notification_statuses_per_service_and_template_for_date',
        return_value=mock_transit_data,
    )

    mock_boto = mocker.patch('app.celery.reporting_tasks.boto3')
    generate_daily_notification_status_csv_report('2021-12-16')

    mock_boto.client.return_value.put_object.assert_called_once()
    _, kwargs = mock_boto.client.return_value.put_object.call_args
    assert kwargs['Key'] == '2021-12-16.stats.csv'
    assert (
        kwargs['Body'] == 'date,service id,service name,template id,template name,status,status reason,count,'
        'channel_type\r\n'
        f'2021-12-16,{service_id},foo,{template_id},bar,delivered,,1,email\r\n'
        f'2021-12-16,{service_id},foo,{template_id},bar,delivered,baz,1,sms\r\n'
    )


@freeze_time('2022-05-08T7:30')
def test_generate_nightly_billing_csv_report(mocker, sample_service, sample_template, sample_notification):
    """
    generate_nightly_billing_csv_report creates a CSV and saves it in AWS S3.  This test checks
    that the appropriate CSV is created and precludes the Boto3 calls to S3.
    """

    process_day = datetime(2022, 5, 8, 7, 30, 0)
    service = sample_service()
    template = sample_template(name='test_sms_template', service=service, template_type=SMS_TYPE)

    sample_notification = sample_notification(
        template=template,
        status='delivered',
        created_at=process_day,
        billing_code='test_code',
        sms_sender_id=service.service_sms_senders[0].id,
        cost_in_millicents=25.0,
    )

    expected_csv = (
        'date,service name,service id,template name,template id,sender,sender id,'
        'billing code,count,channel type,total message parts,total cost\r\n'
        f'2022-05-08,{sample_notification.service.name},{sample_notification.service.id},'
        f'{sample_notification.template.name},{sample_notification.template.id},'
        f'{sample_notification.sms_sender.sms_sender},{sample_notification.sms_sender.id},'
        f'{sample_notification.billing_code},{sample_notification.billable_units},{SMS_TYPE},'
        f'{sample_notification.segments_count},{sample_notification.cost_in_millicents}\r\n'
    )
    process_day_string = str(sample_notification.created_at.date())

    mock_boto = mocker.patch('app.celery.reporting_tasks.boto3')
    generate_nightly_billing_csv_report(process_day_string)
    mock_boto.client.return_value.put_object.assert_called_once_with(
        Body=expected_csv,
        Bucket=current_app.config['NIGHTLY_STATS_BUCKET_NAME'],
        Key=f'{process_day_string}.billing.csv',
    )

from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time

from tests.app.db import (
    create_service_data_retention,
    SMS_TYPE,
)


def test_post_to_get_inbound_sms_with_no_params(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    one = sample_inbound_sms(service)
    two = sample_inbound_sms(service)

    sms = admin_request.post('inbound_sms.post_inbound_sms_for_service', service_id=service.id, _data={})['data']

    assert len(sms) == 2
    assert {inbound['id'] for inbound in sms} == {str(one.id), str(two.id)}
    assert sms[0]['content'] == 'Hello'
    assert set(sms[0].keys()) == {'id', 'created_at', 'service_id', 'notify_number', 'user_number', 'content'}


@pytest.mark.parametrize(
    'user_number',
    [
        '6502532222',
        '+16502532222',
        '+16502532222',
    ],
)
def test_post_to_get_inbound_sms_filters_user_number(
    admin_request,
    sample_inbound_sms,
    sample_service,
    user_number,
):
    service = sample_service()
    # user_number in the db is international and normalised
    one = sample_inbound_sms(service, user_number='+16502532222')
    sample_inbound_sms(service, user_number='+16502532223')

    data = {'phone_number': user_number}

    sms = admin_request.post('inbound_sms.post_inbound_sms_for_service', service_id=service.id, _data=data)['data']

    assert len(sms) == 1
    assert sms[0]['id'] == str(one.id)
    assert sms[0]['user_number'] == str(one.user_number)


def test_post_to_get_inbound_sms_filters_international_user_number(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    # user_number in the db is international and normalised
    one = sample_inbound_sms(service, user_number='+16502532223')
    sample_inbound_sms(service)

    data = {'phone_number': '+1 (650) 253-2223'}

    sms = admin_request.post('inbound_sms.post_inbound_sms_for_service', service_id=service.id, _data=data)['data']

    assert len(sms) == 1
    assert sms[0]['id'] == str(one.id)
    assert sms[0]['user_number'] == str(one.user_number)


def test_post_to_get_inbound_sms_allows_badly_formatted_number(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    one = sample_inbound_sms(service, user_number='ALPHANUM3R1C')

    sms = admin_request.post(
        'inbound_sms.post_inbound_sms_for_service', service_id=service.id, _data={'phone_number': 'ALPHANUM3R1C'}
    )['data']

    assert len(sms) == 1
    assert sms[0]['id'] == str(one.id)
    assert sms[0]['user_number'] == str(one.user_number)


@freeze_time('Monday 10th April 2017 12:00')
# This test assumes the local timezone is EST
def test_post_to_get_most_recent_inbound_sms_for_service_limits_to_a_week(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    sample_inbound_sms(service, created_at=datetime(2017, 4, 3, 3, 59))
    returned_inbound = sample_inbound_sms(service, created_at=datetime(2017, 4, 3, 4, 30))

    sms = admin_request.post('inbound_sms.post_inbound_sms_for_service', service_id=service.id, _data={})

    assert len(sms['data']) == 1
    assert sms['data'][0]['id'] == str(returned_inbound.id)


@pytest.mark.parametrize(
    'days_of_retention, too_old_date, returned_date',
    [
        (5, datetime(2017, 4, 4, 22, 59), datetime(2017, 4, 5, 12, 0)),
        (14, datetime(2017, 3, 26, 22, 59), datetime(2017, 3, 27, 12, 0)),
    ],
)
@freeze_time('Monday 10th April 2017 12:00')
def test_post_to_get_inbound_sms_for_service_respects_data_retention(
    admin_request,
    sample_inbound_sms,
    sample_service,
    days_of_retention,
    too_old_date,
    returned_date,
):
    service = sample_service()
    create_service_data_retention(service, SMS_TYPE, days_of_retention)
    sample_inbound_sms(service, created_at=too_old_date)
    returned_inbound = sample_inbound_sms(service, created_at=returned_date)

    sms = admin_request.post('inbound_sms.post_inbound_sms_for_service', service_id=service.id, _data={})

    assert len(sms['data']) == 1
    assert sms['data'][0]['id'] == str(returned_inbound.id)


def test_get_inbound_sms_summary(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    other_service = sample_service()
    with freeze_time('2017-01-01'):
        sample_inbound_sms(service)
    with freeze_time('2017-01-02'):
        sample_inbound_sms(service)
    with freeze_time('2017-01-03'):
        sample_inbound_sms(other_service)

        summary = admin_request.get('inbound_sms.get_inbound_sms_summary_for_service', service_id=service.id)

    assert summary == {'count': 2, 'most_recent': datetime(2017, 1, 2).isoformat()}


def test_get_inbound_sms_summary_with_no_inbound(admin_request, sample_service):
    summary = admin_request.get('inbound_sms.get_inbound_sms_summary_for_service', service_id=sample_service().id)

    assert summary == {'count': 0, 'most_recent': None}


def test_get_inbound_sms_by_id_returns_200(
    admin_request,
    sample_inbound_sms,
    sample_service_with_inbound_number,
):
    service = sample_service_with_inbound_number(inbound_number='12345')
    inbound = sample_inbound_sms(service=service, user_number='+16502532222')

    response = admin_request.get(
        'inbound_sms.get_inbound_by_id',
        service_id=service.id,
        inbound_sms_id=inbound.id,
    )

    assert response['user_number'] == '+16502532222'
    assert response['service_id'] == str(service.id)


def test_get_inbound_sms_by_id_invalid_id_returns_404(admin_request, sample_service):
    assert admin_request.get(
        'inbound_sms.get_inbound_by_id', service_id=sample_service().id, inbound_sms_id='bar', _expected_status=404
    )


def test_get_inbound_sms_by_id_with_invalid_service_id_returns_404(admin_request):
    assert admin_request.get(
        'inbound_sms.get_inbound_by_id',
        service_id='foo',
        inbound_sms_id='2cfbd6a1-1575-4664-8969-f27be0ea40d9',
        _expected_status=404,
    )


@pytest.mark.parametrize('page_given, expected_rows, has_next_link', [(True, 10, False), (False, 50, True)])
def test_get_most_recent_inbound_sms_for_service(
    admin_request,
    page_given,
    sample_inbound_sms,
    sample_service,
    expected_rows,
    has_next_link,
):
    service = sample_service()
    for i in range(60):
        sample_inbound_sms(service=service, user_number='44770090000{}'.format(i))

    request_args = {'page': 2} if page_given else {}
    response = admin_request.get(
        'inbound_sms.get_most_recent_inbound_sms_for_service', service_id=service.id, **request_args
    )

    assert len(response['data']) == expected_rows
    assert response['has_next'] == has_next_link


@freeze_time('Monday 10th April 2017 12:00')
def test_get_most_recent_inbound_sms_for_service_respects_data_retention(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    create_service_data_retention(service, SMS_TYPE, 5)
    for i in range(10):
        created = datetime.utcnow() - timedelta(days=i)
        sample_inbound_sms(service, user_number='44770090000{}'.format(i), created_at=created)

    response = admin_request.get('inbound_sms.get_most_recent_inbound_sms_for_service', service_id=service.id)

    assert len(response['data']) == 6
    assert [x['created_at'] for x in response['data']] == [
        '2017-04-10T12:00:00.000000Z',
        '2017-04-09T12:00:00.000000Z',
        '2017-04-08T12:00:00.000000Z',
        '2017-04-07T12:00:00.000000Z',
        '2017-04-06T12:00:00.000000Z',
        '2017-04-05T12:00:00.000000Z',
    ]


@freeze_time('Monday 10th April 2017 12:00')
def test_get_most_recent_inbound_sms_for_service_respects_data_retention_if_older_than_a_week(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    create_service_data_retention(service, SMS_TYPE, 14)
    sample_inbound_sms(service, created_at=datetime(2017, 4, 1, 12, 0))

    response = admin_request.get('inbound_sms.get_most_recent_inbound_sms_for_service', service_id=service.id)

    assert len(response['data']) == 1
    assert response['data'][0]['created_at'] == '2017-04-01T12:00:00.000000Z'


@freeze_time('Monday 10th April 2017 12:00')
def test_get_inbound_sms_for_service_respects_data_retention(
    admin_request,
    sample_inbound_sms,
    sample_service,
):
    service = sample_service()
    create_service_data_retention(service, SMS_TYPE, 5)
    for i in range(10):
        created = datetime.utcnow() - timedelta(days=i)
        sample_inbound_sms(service, user_number='44770090000{}'.format(i), created_at=created)

    response = admin_request.get('inbound_sms.get_most_recent_inbound_sms_for_service', service_id=service.id)

    assert len(response['data']) == 6
    assert [x['created_at'] for x in response['data']] == [
        '2017-04-10T12:00:00.000000Z',
        '2017-04-09T12:00:00.000000Z',
        '2017-04-08T12:00:00.000000Z',
        '2017-04-07T12:00:00.000000Z',
        '2017-04-06T12:00:00.000000Z',
        '2017-04-05T12:00:00.000000Z',
    ]

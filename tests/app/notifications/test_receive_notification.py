import base64
import urllib
from datetime import datetime
from unittest.mock import call

import pytest
from flask import json
from freezegun import freeze_time

from app.notifications.receive_notifications import (
    format_mmg_message,
    format_mmg_datetime,
    create_inbound_sms_object,
    strip_leading_forty_four,
    unescape_string,
    fetch_potential_service,
    NoSuitableServiceForInboundSms,
)

from app.models import InboundSms, EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE, Service, Permission
from tests.conftest import set_config, set_config_values
from tests.app.db import create_inbound_number, create_service, create_service_with_inbound_number


def firetext_post(client, data, auth=True, password='testkey'):  # nosec
    headers = [
        ('Content-Type', 'application/x-www-form-urlencoded'),
    ]

    if auth:
        auth_value = base64.b64encode('notify:{}'.format(password).encode('utf-8')).decode('utf-8')
        headers.append(('Authorization', 'Basic ' + auth_value))

    return client.post(path='/notifications/sms/receive/firetext', data=data, headers=headers)


def mmg_post(client, data, auth=True, password='testkey'):  # nosec
    headers = [
        ('Content-Type', 'application/json'),
    ]

    if auth:
        auth_value = base64.b64encode('username:{}'.format(password).encode('utf-8')).decode('utf-8')
        headers.append(('Authorization', 'Basic ' + auth_value))

    return client.post(path='/notifications/sms/receive/mmg', data=json.dumps(data), headers=headers)


def twilio_post(client, data, auth='username:password', signature='signature'):
    headers = [
        ('Content-Type', 'application/x-www-form-urlencoded'),
        ('X-Twilio-Signature', signature),
    ]

    if bool(auth):
        auth_value = base64.b64encode(auth.encode('utf-8')).decode('utf-8')
        headers.append(('Authorization', 'Basic ' + auth_value))

    return client.post(path='/notifications/sms/receive/twilio', data=data, headers=headers)


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_receive_notification_returns_received_to_mmg(client, mocker, sample_service_full_permissions):
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    data = {
        'ID': '1234',
        'MSISDN': '447700900855',
        'Message': 'Some message to notify',
        'Trigger': 'Trigger?',
        'Number': sample_service_full_permissions.inbound_numbers[0].number,
        'Channel': 'SMS',
        'DateReceived': '2012-06-27 12:33:00',
    }
    response = mmg_post(client, data)

    assert response.status_code == 200
    result = json.loads(response.get_data(as_text=True))
    assert result['status'] == 'ok'

    inbound_sms_id = InboundSms.query.all()[0].id
    mocked.assert_called_once_with(
        [str(inbound_sms_id), str(sample_service_full_permissions.id)], queue='notify-internal-tasks'
    )


@pytest.mark.parametrize(
    'permissions,expected_response',
    [
        ([SMS_TYPE, INBOUND_SMS_TYPE], True),
        ([INBOUND_SMS_TYPE], False),
        ([SMS_TYPE], False),
    ],
)
def test_check_permissions_for_inbound_sms(notify_db, notify_db_session, permissions, expected_response):
    service = create_service(service_permissions=permissions)
    assert service.has_permissions([INBOUND_SMS_TYPE, SMS_TYPE]) is expected_response


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@pytest.mark.parametrize(
    'permissions',
    [
        [SMS_TYPE],
        [INBOUND_SMS_TYPE],
    ],
)
def test_receive_notification_from_twilio_without_permissions_does_not_persist(
    client, mocker, notify_db_session, permissions
):
    mocker.patch('twilio.request_validator.RequestValidator.validate', return_value=True)

    service = create_service_with_inbound_number(inbound_number='+61412888888', service_permissions=permissions)
    mocker.patch('app.notifications.receive_notifications.dao_fetch_service_by_inbound_number', return_value=service)
    mocked_send_inbound_sms = mocker.patch(
        'app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async'
    )
    mocker.patch('app.notifications.receive_notifications.has_inbound_sms_permissions', return_value=False)

    data = urllib.parse.urlencode(
        {'MessageSid': '1', 'From': '+61412999999', 'To': '+61412888888', 'Body': 'this is a message'}
    )

    response = twilio_post(client, data)

    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<?xml version="1.0" encoding="UTF-8"?><Response />'
    assert InboundSms.query.count() == 0
    assert not mocked_send_inbound_sms.called


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_twilio_receive_notification_without_permissions_does_not_create_inbound_even_with_inbound_number_set(
    client, mocker, sample_service
):
    mocker.patch('twilio.request_validator.RequestValidator.validate', return_value=True)

    create_inbound_number('+61412345678', service_id=sample_service.id, active=True)

    mocked_send_inbound_sms = mocker.patch(
        'app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async'
    )
    mocked_has_permissions = mocker.patch(
        'app.notifications.receive_notifications.has_inbound_sms_permissions', return_value=False
    )

    data = urllib.parse.urlencode(
        {'MessageSid': '1', 'From': '+61412999999', 'To': '+61412345678', 'Body': 'this is a message'}
    )

    response = twilio_post(client, data)

    assert response.status_code == 200
    assert len(InboundSms.query.all()) == 0
    assert mocked_has_permissions.called
    mocked_send_inbound_sms.assert_not_called()


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@pytest.mark.parametrize(
    'permissions',
    [
        [SMS_TYPE],
        [INBOUND_SMS_TYPE],
    ],
)
def test_receive_notification_from_mmg_without_permissions_does_not_persist(
    client, mocker, notify_db_session, permissions
):
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    create_service_with_inbound_number(inbound_number='07111111111', service_permissions=permissions)
    data = {
        'ID': '1234',
        'MSISDN': '07111111111',
        'Message': 'Some message to notify',
        'Trigger': 'Trigger?',
        'Number': 'testing',
        'Channel': 'SMS',
        'DateReceived': '2012-06-27 12:33:00',
    }
    response = mmg_post(client, data)

    assert response.status_code == 200
    assert response.get_data(as_text=True) == 'RECEIVED'
    assert InboundSms.query.count() == 0
    assert mocked.called is False


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_receive_notification_from_twilio_responds(notify_db_session, client, mocker):
    mocker.patch('twilio.request_validator.RequestValidator.validate', return_value=True)
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    mock = mocker.patch('app.notifications.receive_notifications.statsd_client.incr')

    service = create_service_with_inbound_number(
        service_name='b', inbound_number='+61412888888', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = urllib.parse.urlencode(
        {'MessageSid': '1', 'From': '+61412999999', 'To': '+61412888888', 'Body': 'this is a message'}
    )

    response = twilio_post(client, data)

    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<?xml version="1.0" encoding="UTF-8"?><Response />'
    mock.assert_has_calls([call('inbound.twilio.successful')])
    inbound_sms_id = InboundSms.query.all()[0].id
    mocked.assert_called_once_with([str(inbound_sms_id), str(service.id)], queue='notify-internal-tasks')


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@freeze_time('2017-01-01T01:00:00')
def test_receive_notification_from_twilio_persists_message(notify_db_session, client, mocker):
    mocker.patch('twilio.request_validator.RequestValidator.validate', return_value=True)
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    mocker.patch('app.notifications.receive_notifications.statsd_client.incr')

    service = create_service_with_inbound_number(
        inbound_number='+61412345678', service_name='b', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = urllib.parse.urlencode(
        {'MessageSid': '1', 'From': '+61487654321', 'To': '+61412345678', 'Body': 'this is a message'}
    )

    twilio_post(client, data)

    persisted = InboundSms.query.first()
    assert persisted is not None
    assert persisted.notify_number == '+61412345678'
    assert persisted.user_number == '+61487654321'
    assert persisted.service == service
    assert persisted.content == 'this is a message'
    assert persisted.provider == 'twilio'
    assert persisted.provider_date == datetime(2017, 1, 1, 1, 0, 0, 0)
    mocked.assert_called_once_with([str(persisted.id), str(service.id)], queue='notify-internal-tasks')


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_twilio_no_service_matches_inbound_number(notify_db_session, client, mocker):
    mocker.patch('twilio.request_validator.RequestValidator.validate', return_value=True)
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    mock = mocker.patch('app.notifications.receive_notifications.statsd_client.incr')

    create_service_with_inbound_number(
        inbound_number='+61412345678', service_name='b', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = urllib.parse.urlencode(
        {'MessageSid': '1', 'From': '+61412999999', 'To': '+61412000000', 'Body': 'this is a message'}
    )

    response = twilio_post(client, data)

    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<?xml version="1.0" encoding="UTF-8"?><Response />'
    assert not InboundSms.query.all()
    mock.assert_has_calls([call('inbound.twilio.failed')])
    mocked.call_count == 0


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_twilio_inbound_sms_fails_if_incorrect_signature(notify_db_session, notify_api, client, mocker):
    mocker.patch('twilio.request_validator.RequestValidator.validate', return_value=False)

    data = urllib.parse.urlencode(
        {'MessageSid': '1', 'From': '+61412999999', 'To': '+61412345678', 'Body': 'this is a message'}
    )

    response = twilio_post(client, data)
    assert response.status_code == 400


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@pytest.mark.parametrize(
    'auth, usernames, passwords, status_code',
    [
        ['username:password', ['username'], ['password'], 200],
        ['username2:password', ['username', 'username2'], ['password'], 200],
        ['username:password2', ['username'], ['password', 'password2'], 200],
        ['', ['username'], ['password'], 401],
        ['', [], [], 401],
        ['username', ['username'], ['password'], 401],
        ['username:', ['username'], ['password'], 403],
        [':password', ['username'], ['password'], 403],
        ['wrong:password', ['username'], ['password'], 403],
        ['username:wrong', ['username'], ['password'], 403],
        ['username:password', [], [], 403],
    ],
)
def test_twilio_inbound_sms_auth(
    notify_db_session, notify_api, client, mocker, auth, usernames, passwords, status_code
):
    mocker.patch('twilio.request_validator.RequestValidator.validate', return_value=True)
    mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')

    create_service_with_inbound_number(
        service_name='b', inbound_number='+61412345678', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = urllib.parse.urlencode(
        {'MessageSid': '1', 'From': '+61412999999', 'To': '+61412345678', 'Body': 'this is a message'}
    )

    with set_config_values(
        notify_api,
        {
            'TWILIO_INBOUND_SMS_USERNAMES': usernames,
            'TWILIO_INBOUND_SMS_PASSWORDS': passwords,
        },
    ):
        response = twilio_post(client, data, auth=auth)
        assert response.status_code == status_code


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@pytest.mark.parametrize(
    'permissions',
    [
        [SMS_TYPE],
        [INBOUND_SMS_TYPE],
    ],
)
def test_receive_notification_from_firetext_without_permissions_does_not_persist(
    client, mocker, notify_db_session, permissions
):
    service = create_service_with_inbound_number(inbound_number='07111111111', service_permissions=permissions)
    mocker.patch('app.notifications.receive_notifications.dao_fetch_service_by_inbound_number', return_value=service)
    mocked_send_inbound_sms = mocker.patch(
        'app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async'
    )
    mocker.patch('app.notifications.receive_notifications.has_inbound_sms_permissions', return_value=False)

    data = 'source=07999999999&destination=07111111111&message=this is a message&time=2017-01-01 12:00:00'
    response = firetext_post(client, data)

    assert response.status_code == 200
    result = json.loads(response.get_data(as_text=True))

    assert result['status'] == 'ok'
    assert InboundSms.query.count() == 0
    assert not mocked_send_inbound_sms.called


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_receive_notification_without_permissions_does_not_create_inbound_even_with_inbound_number_set(
    client, mocker, sample_service
):
    inbound_number = create_inbound_number('1', service_id=sample_service.id, active=True)

    mocked_send_inbound_sms = mocker.patch(
        'app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async'
    )
    mocked_has_permissions = mocker.patch(
        'app.notifications.receive_notifications.has_inbound_sms_permissions', return_value=False
    )

    data = {
        'ID': '1234',
        'MSISDN': '447700900855',
        'Message': 'Some message to notify',
        'Trigger': 'Trigger?',
        'Number': inbound_number.number,
        'Channel': 'SMS',
        'DateReceived': '2012-06-27 12:33:00',
    }

    response = mmg_post(client, data)

    assert response.status_code == 200
    assert len(InboundSms.query.all()) == 0
    assert mocked_has_permissions.called
    mocked_send_inbound_sms.assert_not_called()


@pytest.mark.parametrize(
    'message, expected_output',
    [
        ('abc', 'abc'),
        ('', ''),
        ('lots+of+words', 'lots of words'),
        ('%F0%9F%93%A9+%F0%9F%93%A9+%F0%9F%93%A9', '📩 📩 📩'),
        ('x+%2B+y', 'x + y'),
    ],
)
def test_format_mmg_message(message, expected_output):
    assert format_mmg_message(message) == expected_output


@pytest.mark.parametrize(
    'raw, expected',
    [
        (
            '😬',
            '😬',
        ),
        (
            '1\\n2',
            '1\n2',
        ),
        (
            "\\'\"\\'",
            "'\"'",
        ),
        (
            """

        """,
            """

        """,
        ),
        (
            '\x79 \\x79 \\\\x79',  # we should never see the middle one
            'y y \\x79',
        ),
    ],
)
def test_unescape_string(raw, expected):
    assert unescape_string(raw) == expected


@pytest.mark.parametrize(
    'provider_date, expected_output',
    [
        ('2017-01-21+11%3A56%3A11', datetime(2017, 1, 21, 16, 56, 11)),
        ('2017-05-21+11%3A56%3A11', datetime(2017, 5, 21, 15, 56, 11)),
    ],
)
# This test assumes the local timezone is EST
def test_format_mmg_datetime(provider_date, expected_output):
    assert format_mmg_datetime(provider_date) == expected_output


# This test assumes the local timezone is EST
def test_create_inbound_mmg_sms_object(sample_service_full_permissions):
    data = {
        'Message': 'hello+there+%F0%9F%93%A9',
        'Number': '+15551234567',
        'MSISDN': '447700900001',
        'DateReceived': '2017-01-02+03%3A04%3A05',
        'ID': 'bar',
    }

    inbound_sms = create_inbound_sms_object(
        sample_service_full_permissions,
        format_mmg_message(data['Message']),
        data['Number'],
        data['MSISDN'],
        data['ID'],
        format_mmg_datetime(data['DateReceived']),
        'mmg',
    )

    assert inbound_sms.service_id == sample_service_full_permissions.id
    assert inbound_sms.notify_number == '+15551234567'
    assert inbound_sms.user_number == '447700900001'
    assert inbound_sms.provider_date == datetime(2017, 1, 2, 8, 4, 5)
    assert inbound_sms.provider_reference == 'bar'
    assert inbound_sms._content != 'hello there 📩'
    assert inbound_sms.content == 'hello there 📩'
    assert inbound_sms.provider == 'mmg'


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@pytest.mark.parametrize('notify_number', ['foo', 'baz'], ids=['two_matching_services', 'no_matching_services'])
def test_mmg_receive_notification_error_if_not_single_matching_service(client, notify_db_session, notify_number):
    create_service_with_inbound_number(
        inbound_number='dog', service_name='a', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )
    create_service_with_inbound_number(
        inbound_number='bar', service_name='b', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = {
        'Message': 'hello',
        'Number': notify_number,
        'MSISDN': '7700900001',
        'DateReceived': '2017-01-02 03:04:05',
        'ID': 'bar',
    }
    response = mmg_post(client, data)

    # we still return 'RECEIVED' to MMG
    assert response.status_code == 200
    assert response.get_data(as_text=True) == 'RECEIVED'
    assert InboundSms.query.count() == 0


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_receive_notification_returns_received_to_firetext(notify_db_session, client, mocker):
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    mock = mocker.patch('app.notifications.receive_notifications.statsd_client.incr')

    service = create_service_with_inbound_number(
        service_name='b', inbound_number='07111111111', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = 'source=07999999999&destination=07111111111&message=this is a message&time=2017-01-01 12:00:00'

    response = firetext_post(client, data)

    assert response.status_code == 200
    result = json.loads(response.get_data(as_text=True))

    mock.assert_has_calls([call('inbound.firetext.successful')])

    assert result['status'] == 'ok'
    inbound_sms_id = InboundSms.query.all()[0].id
    mocked.assert_called_once_with([str(inbound_sms_id), str(service.id)], queue='notify-internal-tasks')


# This test assumes the local timezone is EST
@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_receive_notification_from_firetext_persists_message(notify_db_session, client, mocker):
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    mocker.patch('app.notifications.receive_notifications.statsd_client.incr')

    service = create_service_with_inbound_number(
        inbound_number='07111111111', service_name='b', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = 'source=447999999999&destination=07111111111&message=this is a message&time=2017-01-01 12:00:00'

    response = firetext_post(client, data)

    assert response.status_code == 200
    result = json.loads(response.get_data(as_text=True))

    persisted = InboundSms.query.first()
    assert result['status'] == 'ok'
    assert persisted.notify_number == '07111111111'
    assert persisted.user_number == '447999999999'
    assert persisted.service == service
    assert persisted.content == 'this is a message'
    assert persisted.provider == 'firetext'
    assert persisted.provider_date == datetime(2017, 1, 1, 17, 0, 0, 0)
    mocked.assert_called_once_with([str(persisted.id), str(service.id)], queue='notify-internal-tasks')


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_receive_notification_from_firetext_persists_message_with_normalized_phone(notify_db_session, client, mocker):
    mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    mocker.patch('app.notifications.receive_notifications.statsd_client.incr')

    create_service_with_inbound_number(
        inbound_number='07111111111', service_name='b', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = 'source=(+44)7999999999&destination=07111111111&message=this is a message&time=2017-01-01 12:00:00'

    response = firetext_post(client, data)

    assert response.status_code == 200
    result = json.loads(response.get_data(as_text=True))

    persisted = InboundSms.query.first()

    assert result['status'] == 'ok'
    assert persisted.user_number == '( 44)7999999999'


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_returns_ok_to_firetext_if_mismatched_sms_sender(notify_db_session, client, mocker):
    mocked = mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')
    mock = mocker.patch('app.notifications.receive_notifications.statsd_client.incr')

    create_service_with_inbound_number(
        inbound_number='07111111199', service_name='b', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = 'source=(+44)7999999999&destination=07111111111&message=this is a message&time=2017-01-01 12:00:00'

    response = firetext_post(client, data)

    assert response.status_code == 200
    result = json.loads(response.get_data(as_text=True))

    assert not InboundSms.query.all()
    assert result['status'] == 'ok'
    mock.assert_has_calls([call('inbound.firetext.failed')])
    mocked.call_count == 0


@pytest.mark.parametrize(
    'number, expected',
    [
        ('447123123123', '07123123123'),
        ('447123123144', '07123123144'),
        ('07123123123', '07123123123'),
        ('447444444444', '07444444444'),
    ],
)
def test_strip_leading_country_code(number, expected):
    assert strip_leading_forty_four(number) == expected


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@pytest.mark.parametrize(
    'auth, keys, status_code',
    [
        ['testkey', ['testkey'], 200],
        ['', ['testkey'], 401],
        ['wrong', ['testkey'], 403],
        ['testkey1', ['testkey1', 'testkey2'], 200],
        ['testkey2', ['testkey1', 'testkey2'], 200],
        ['wrong', ['testkey1', 'testkey2'], 403],
        ['', [], 401],
        ['testkey', [], 403],
    ],
)
def test_firetext_inbound_sms_auth(notify_db_session, notify_api, client, mocker, auth, keys, status_code):
    mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')

    create_service_with_inbound_number(
        service_name='b', inbound_number='07111111111', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = 'source=07999999999&destination=07111111111&message=this is a message&time=2017-01-01 12:00:00'

    with set_config(notify_api, 'FIRETEXT_INBOUND_SMS_AUTH', keys):
        response = firetext_post(client, data, auth=bool(auth), password=auth)
        assert response.status_code == status_code


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
@pytest.mark.parametrize(
    'auth, keys, status_code',
    [
        ['testkey', ['testkey'], 200],
        ['', ['testkey'], 401],
        ['wrong', ['testkey'], 403],
        ['testkey1', ['testkey1', 'testkey2'], 200],
        ['testkey2', ['testkey1', 'testkey2'], 200],
        ['wrong', ['testkey1', 'testkey2'], 403],
        ['', [], 401],
        ['testkey', [], 403],
    ],
)
def test_mmg_inbound_sms_auth(notify_db_session, notify_api, client, mocker, auth, keys, status_code):
    mocker.patch('app.notifications.receive_notifications.send_inbound_sms_to_service.apply_async')

    create_service_with_inbound_number(
        service_name='b', inbound_number='07111111111', service_permissions=[EMAIL_TYPE, SMS_TYPE, INBOUND_SMS_TYPE]
    )

    data = {
        'ID': '1234',
        'MSISDN': '07111111111',
        'Message': 'Some message to notify',
        'Trigger': 'Trigger?',
        'Number': 'testing',
        'Channel': 'SMS',
        'DateReceived': '2012-06-27 12:33:00',
    }

    with set_config(notify_api, 'MMG_INBOUND_SMS_AUTH', keys):
        response = mmg_post(client, data, auth=bool(auth), password=auth)
        assert response.status_code == status_code


@freeze_time('2017-01-01T16:00:00')
def test_create_inbound_sms_object(sample_service_full_permissions):
    inbound_sms = create_inbound_sms_object(
        service=sample_service_full_permissions,
        content='hello there 📩',
        notify_number='+15551234567',
        from_number='+61412345678',
        provider_ref='bar',
        date_received=datetime.utcnow(),
        provider_name='twilio',
    )

    assert inbound_sms.service_id == sample_service_full_permissions.id
    assert inbound_sms.notify_number == '+15551234567'
    assert inbound_sms.user_number == '+61412345678'
    assert inbound_sms.provider_date == datetime(2017, 1, 1, 16, 00, 00)
    assert inbound_sms.provider_reference == 'bar'
    assert inbound_sms._content != 'hello there 📩'
    assert inbound_sms.content == 'hello there 📩'
    assert inbound_sms.provider == 'twilio'


def test_create_inbound_sms_object_works_with_alphanumeric_sender(sample_service_full_permissions):
    data = {
        'Message': 'hello',
        'Number': '+15551234567',
        'MSISDN': 'ALPHANUM3R1C',
        'DateReceived': '2017-01-02+03%3A04%3A05',
        'ID': 'bar',
    }

    inbound_sms = create_inbound_sms_object(
        service=sample_service_full_permissions,
        content=format_mmg_message(data['Message']),
        notify_number='+15551234567',
        from_number='ALPHANUM3R1C',
        provider_ref='foo',
        date_received=None,
        provider_name='mmg',
    )

    assert inbound_sms.user_number == 'ALPHANUM3R1C'


class TestFetchPotentialService:
    def test_should_raise_if_no_matching_service(self, notify_api, mocker):
        mocker.patch('app.notifications.receive_notifications.dao_fetch_service_by_inbound_number', return_value=None)

        with pytest.raises(NoSuitableServiceForInboundSms):
            fetch_potential_service('some-inbound-number', 'some-provider-name')

    def test_should_raise_if_service_doesnt_have_permission(self, notify_api, mocker):
        # make mocked service execute original code
        # just mocking service won't let us execute .has_permissions
        # method properly
        mock_service_instance = Service(permissions=[])
        mocker.patch(
            'app.notifications.receive_notifications.dao_fetch_service_by_inbound_number',
            return_value=mock_service_instance,
        )

        with pytest.raises(NoSuitableServiceForInboundSms):
            fetch_potential_service('some-inbound-number', 'some-provider-name')

    def test_should_return_service_with_permission(self, notify_api, mocker):
        service = mocker.Mock(
            Service,
            permissions=[
                mocker.Mock(Permission, permission=INBOUND_SMS_TYPE),
                mocker.Mock(Permission, permission=SMS_TYPE),
            ],
        )
        mocker.patch(
            'app.notifications.receive_notifications.dao_fetch_service_by_inbound_number', return_value=service
        )

        assert fetch_potential_service('some-inbound-number', 'some-provider-name') == service

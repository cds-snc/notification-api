from datetime import datetime

import pytest

from app.notifications.receive_notifications import (
    format_mmg_message,
    format_mmg_datetime,
    create_inbound_sms_object,
    strip_leading_forty_four,
    has_inbound_sms_permissions,
    unescape_string,
)

from app.models import SMS_TYPE, INBOUND_SMS_TYPE
from tests.app.db import create_service


@pytest.mark.parametrize('permissions,expected_response', [
    ([SMS_TYPE, INBOUND_SMS_TYPE], True),
    ([INBOUND_SMS_TYPE], False),
    ([SMS_TYPE], False),
])
def test_check_permissions_for_inbound_sms(notify_db, notify_db_session, permissions, expected_response):
    service = create_service(service_permissions=permissions)
    assert has_inbound_sms_permissions(service.permissions) is expected_response


@pytest.mark.parametrize('message, expected_output', [
    ('abc', 'abc'),
    ('', ''),
    ('lots+of+words', 'lots of words'),
    ('%F0%9F%93%A9+%F0%9F%93%A9+%F0%9F%93%A9', '📩 📩 📩'),
    ('x+%2B+y', 'x + y')
])
def test_format_mmg_message(message, expected_output):
    assert format_mmg_message(message) == expected_output


@pytest.mark.parametrize('raw, expected', [
    (
        '😬',
        '😬',
    ),
    (
        '1\\n2',
        '1\n2',
    ),
    (
        '\\\'"\\\'',
        '\'"\'',
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
])
def test_unescape_string(raw, expected):
    assert unescape_string(raw) == expected


@pytest.mark.parametrize('provider_date, expected_output', [
    ('2017-01-21+11%3A56%3A11', datetime(2017, 1, 21, 16, 56, 11)),
    ('2017-05-21+11%3A56%3A11', datetime(2017, 5, 21, 15, 56, 11))
])
# This test assumes the local timezone is EST
def test_format_mmg_datetime(provider_date, expected_output):
    assert format_mmg_datetime(provider_date) == expected_output


# This test assumes the local timezone is EST
def test_create_inbound_mmg_sms_object(sample_service_full_permissions):
    data = {
        'Message': 'hello+there+%F0%9F%93%A9',
        'Number': sample_service_full_permissions.get_inbound_number(),
        'MSISDN': '447700900001',
        'DateRecieved': '2017-01-02+03%3A04%3A05',
        'ID': 'bar',
    }

    inbound_sms = create_inbound_sms_object(sample_service_full_permissions, format_mmg_message(data["Message"]),
                                            data["MSISDN"], data["ID"], data["DateRecieved"], "mmg")

    assert inbound_sms.service_id == sample_service_full_permissions.id
    assert inbound_sms.notify_number == sample_service_full_permissions.get_inbound_number()
    assert inbound_sms.user_number == '447700900001'
    assert inbound_sms.provider_date == datetime(2017, 1, 2, 8, 4, 5)
    assert inbound_sms.provider_reference == 'bar'
    assert inbound_sms._content != 'hello there 📩'
    assert inbound_sms.content == 'hello there 📩'
    assert inbound_sms.provider == 'mmg'


def test_create_inbound_mmg_sms_object_uses_inbound_number_if_set(sample_service_full_permissions):
    sample_service_full_permissions.sms_sender = 'foo'
    inbound_number = sample_service_full_permissions.get_inbound_number()

    data = {
        'Message': 'hello+there+%F0%9F%93%A9',
        'Number': sample_service_full_permissions.get_inbound_number(),
        'MSISDN': '07700 900 001',
        'DateRecieved': '2017-01-02+03%3A04%3A05',
        'ID': 'bar',
    }

    inbound_sms = create_inbound_sms_object(
        sample_service_full_permissions,
        format_mmg_message(data["Message"]),
        data["MSISDN"],
        data["ID"],
        data["DateRecieved"],
        "mmg"
    )

    assert inbound_sms.service_id == sample_service_full_permissions.id
    assert inbound_sms.notify_number == inbound_number


@pytest.mark.parametrize(
    'number, expected',
    [
        ('447123123123', '07123123123'),
        ('447123123144', '07123123144'),
        ('07123123123', '07123123123'),
        ('447444444444', '07444444444')
    ]
)
def test_strip_leading_country_code(number, expected):
    assert strip_leading_forty_four(number) == expected


def test_create_inbound_sms_object_works_with_alphanumeric_sender(sample_service_full_permissions):
    data = {
        'Message': 'hello',
        'Number': sample_service_full_permissions.get_inbound_number(),
        'MSISDN': 'ALPHANUM3R1C',
        'DateRecieved': '2017-01-02+03%3A04%3A05',
        'ID': 'bar',
    }

    inbound_sms = create_inbound_sms_object(
        service=sample_service_full_permissions,
        content=format_mmg_message(data["Message"]),
        from_number='ALPHANUM3R1C',
        provider_ref='foo',
        date_received=None,
        provider_name="mmg"
    )

    assert inbound_sms.user_number == 'ALPHANUM3R1C'

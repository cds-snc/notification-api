from datetime import datetime
from random import randint
from uuid import uuid4

import pytest
from freezegun import freeze_time

from app.constants import INBOUND_SMS_TYPE, SMS_TYPE, TWILIO_PROVIDER
from app.models import Permission, Service
from app.notifications.receive_notifications import (
    NoSuitableServiceForInboundSms,
    create_inbound_sms_object,
    fetch_potential_service,
)


@pytest.mark.parametrize(
    'permissions,expected_response',
    [
        ([SMS_TYPE, INBOUND_SMS_TYPE], True),
        ([INBOUND_SMS_TYPE], False),
        ([SMS_TYPE], False),
    ],
)
def test_check_permissions_for_inbound_sms(
    permissions,
    expected_response,
    sample_service,
):
    service = sample_service(service_permissions=permissions)
    assert service.has_permissions([INBOUND_SMS_TYPE, SMS_TYPE]) is expected_response


@freeze_time('2017-01-01T16:00:00')
def test_create_inbound_sms_object(
    sample_service,
):
    service = sample_service()
    ref = str(uuid4())
    number = f'+1{randint(1000000000, 9999999999)}'
    inbound_sms = create_inbound_sms_object(
        service=service,
        content='hello there 📩',
        notify_number=number,
        from_number='+61412345678',
        provider_ref=ref,
        date_received=datetime.utcnow(),
        provider_name=TWILIO_PROVIDER,
    )

    assert inbound_sms.service_id == service.id
    assert inbound_sms.notify_number == number
    assert inbound_sms.user_number == '+61412345678'
    assert inbound_sms.provider_date == datetime(2017, 1, 1, 16, 00, 00)
    assert inbound_sms.provider_reference == ref
    assert inbound_sms._content != 'hello there 📩'
    assert inbound_sms.content == 'hello there 📩'
    assert inbound_sms.provider == TWILIO_PROVIDER


def test_create_inbound_sms_object_logs_invalid_from_number(
    notify_api,
    mocker,
    sample_service,
):
    service = sample_service()
    ref = str(uuid4())
    number = '+16502532222'
    invalid_from_number = 'ALPHANUM3R1C'

    mock_logger = mocker.patch('notifications_utils.recipients.logging.exception')

    inbound_sms = create_inbound_sms_object(
        service=service,
        content='no matter where you go, there you are',
        notify_number=number,
        from_number=invalid_from_number,
        provider_ref=ref,
        date_received=datetime.utcnow(),
        provider_name=TWILIO_PROVIDER,
    )

    assert inbound_sms.service_id == service.id
    assert inbound_sms.notify_number == number
    assert inbound_sms.user_number == invalid_from_number
    assert inbound_sms.content == 'no matter where you go, there you are'

    mock_logger.assert_called_with(
        f'Inbound SMS service_id: {service.id} ({service.name}), Invalid from_number received: {invalid_from_number}'
    )


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

import base64
import json
from datetime import datetime

import pytest
from freezegun import freeze_time

from app.celery.process_pinpoint_inbound_sms import process_pinpoint_inbound_sms, CeleryEvent, \
    PinpointInboundSmsMessage, NoSuitableServiceForInboundSms
from app.feature_flags import FeatureFlag
from app.models import Service


@pytest.fixture
def toggle_enabled(mocker):
    mocker.patch('app.celery.process_pinpoint_inbound_sms.is_feature_enabled', return_value=True)


def test_passes_if_toggle_disabled(mocker, db_session):
    mock_toggle = mocker.patch('app.celery.process_pinpoint_inbound_sms.is_feature_enabled', return_value=False)

    process_pinpoint_inbound_sms(event={})

    mock_toggle.assert_called_with(FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED)


def test_fails_if_no_matching_service(mocker, db_session, toggle_enabled):
    mock_fetch_potential_service = mocker.patch(
        'app.celery.process_pinpoint_inbound_sms.fetch_potential_service',
        return_value=False
    )

    destination_number = "1234"

    with pytest.raises(NoSuitableServiceForInboundSms):
        process_pinpoint_inbound_sms(event=_pinpoint_inbound_sms_event(destination_number))

    mock_fetch_potential_service.assert_called_with(destination_number, 'pinpoint')


@freeze_time("2016-11-12 11:23:47")
def test_creates_inbound_sms_object_with_correct_fields(mocker, db_session, toggle_enabled):
    mock_service = mocker.Mock(Service)
    mocker.patch('app.celery.process_pinpoint_inbound_sms.fetch_potential_service', return_value=mock_service)

    mock_create_inbound_sms_object = mocker.patch(
        'app.celery.process_pinpoint_inbound_sms.create_inbound_sms_object'
    )

    message_body = 'hello this is a message body'
    origination_number = '555'
    inbound_message_id = 'abc123'

    event = _pinpoint_inbound_sms_event(
        message_body=message_body,
        origination_number=origination_number,
        inbound_message_id=inbound_message_id
    )
    process_pinpoint_inbound_sms(event=event)

    _, kwargs = mock_create_inbound_sms_object.call_args
    assert kwargs['service'] == mock_service
    assert kwargs['content'] == message_body
    assert kwargs['from_number'] == origination_number
    assert kwargs['provider_ref'] == inbound_message_id
    assert kwargs['date_received'] == datetime(2016, 11, 12, 11, 23, 47)
    assert kwargs['provider_name'] == 'pinpoint'


def _pinpoint_inbound_sms_event(
        message_body: str = 'some message body',
        destination_number: str = '1234',
        origination_number: str = '5678',
        inbound_message_id: str = 'some id'
) -> CeleryEvent:

    pinpoint_message: PinpointInboundSmsMessage = {
        'messageBody': message_body,
        'destinationNumber': destination_number,
        'originationNumber': origination_number,
        'inboundMessageId': inbound_message_id
    }
    return {
        'Message': base64.b64encode(bytes(json.dumps(pinpoint_message), 'utf-8')).decode('utf-8')
    }

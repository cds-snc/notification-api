import base64
import json

import pytest

from app.celery.process_pinpoint_inbound_sms import process_pinpoint_inbound_sms, CeleryEvent, \
    PinpointInboundSmsMessage, NoSuitableServiceForInboundSms
from app.feature_flags import FeatureFlag


def test_passes_if_toggle_disabled(mocker, db_session):
    mock_toggle = mocker.patch('app.celery.process_pinpoint_inbound_sms.is_feature_enabled', return_value=False)

    process_pinpoint_inbound_sms(event={})

    mock_toggle.assert_called_with(FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED)


def test_fails_if_no_matching_service(mocker, db_session):
    mocker.patch('app.celery.process_pinpoint_inbound_sms.is_feature_enabled', return_value=True)

    mock_fetch_potential_service = mocker.patch(
        'app.celery.process_pinpoint_inbound_sms.fetch_potential_service',
        return_value=False
    )

    destination_number = "1234"

    with pytest.raises(NoSuitableServiceForInboundSms):
        process_pinpoint_inbound_sms(event=_pinpoint_inbound_sms_event(destination_number))

    mock_fetch_potential_service.assert_called_with(destination_number, 'pinpoint')


def _pinpoint_inbound_sms_event(destination_number: str) -> CeleryEvent:
    pinpoint_message: PinpointInboundSmsMessage = {
        "messageBody": 'foo',
        "destinationNumber": destination_number,
        "originationNumber": '5678'
    }
    return {
        'Message': base64.b64encode(bytes(json.dumps(pinpoint_message), 'utf-8')).decode('utf-8')
    }

from app.celery.process_pinpoint_inbound_sms import process_pinpoint_inbound_sms
from app.feature_flags import FeatureFlag


def test_passes_if_toggle_disabled(mocker, db_session):
    mock_toggle = mocker.patch('app.celery.process_pinpoint_inbound_sms.is_feature_enabled', return_value=False)

    process_pinpoint_inbound_sms(event={})

    mock_toggle.assert_called_with(FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED)

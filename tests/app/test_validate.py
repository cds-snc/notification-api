import pytest
from app.schema_validation import validate
from app.v2.notifications.notification_schemas import post_sms_request
from jsonschema import ValidationError


def test_validate_v2_notifications_redaction(notify_api, caplog):
    """
    When POST data validation fails for a Notification, the request body
    should be logged with personalized information redacted.
    """

    # This is not valid POST data.
    notification_POST_request_data = {
        'personalisation': {
            'sensitive_data': "Don't reveal this!",
        },
    }

    with pytest.raises(ValidationError):
        validate(notification_POST_request_data, post_sms_request)

    for record in caplog.records:
        assert record.args['personalisation']['sensitive_data'] == '<redacted>'

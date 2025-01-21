import pytest
from app.schema_validation import validate
from app.v2.notifications.notification_schemas import post_sms_request
from jsonschema import ValidationError


def test_validate_v2_notifications_personalisation_redaction(notify_api, mocker):
    """
    When POST data validation fails for a Notification, the request body
    should be logged with personalized information redacted.
    """
    mock_logger = mocker.patch('app.schema_validation.current_app.logger.info')

    # This is not valid POST data.
    notification_POST_request_data = {
        'personalisation': {
            'sensitive_data': "Don't reveal this!",
        },
    }

    with pytest.raises(ValidationError):
        validate(notification_POST_request_data, post_sms_request)

    # Cannot use a variable with loggers and assertions, falsely passes assertions
    mock_logger.assert_called_once_with(
        'Validation failed for: %s', {'personalisation': {'sensitive_data': '<redacted>'}}
    )


@pytest.mark.parametrize(
    'personalisation_value',
    [
        ['hello', 'world'],
        'a string',
        12345,
        {'personalization': 'spelled it wrong'},
    ],
)
def test_validate_v2_notifications_personalisation_redaction_unexpected_format(
    notify_api,
    mocker,
    personalisation_value,
):
    """
    When POST data validation fails for a Notification, the request body
    should be logged with personalized information redacted.
    """
    mock_logger = mocker.patch('app.schema_validation.current_app.logger.info')
    with pytest.raises(ValidationError):
        validate({'personalisation': personalisation_value}, post_sms_request)

    # Cannot use a variable with loggers and assertions, falsely passes assertions
    if isinstance(personalisation_value, dict):
        mock_logger.assert_called_once_with(
            'Validation failed for: %s', {'personalisation': {key: '<redacted>' for key in personalisation_value}}
        )
    else:
        mock_logger.assert_called_once_with('Validation failed for: %s', {'personalisation': '<redacted>'})


def test_validate_v2_notifications_icn_redaction(
    notify_api,
    mocker,
):
    """
    When POST data validation fails for a Notification, the request body
    should be logged with personalized information redacted.
    """
    mock_logger = mocker.patch('app.schema_validation.current_app.logger.info')
    with pytest.raises(ValidationError):
        validate({'recipient_identifier': {'id_type': 'ICN', 'id_value': '1234567890'}}, post_sms_request)

    # Cannot use a variable with loggers and assertions, falsely passes assertions
    mock_logger.assert_called_once_with(
        'Validation failed for: %s', {'recipient_identifier': {'id_type': 'ICN', 'id_value': '<redacted>'}}
    )


@pytest.mark.parametrize(
    'recipient_identifier_value',
    [
        ['hello', 'world'],
        'a string',
        12345,
        {'id_value': 'not id_type'},
    ],
)
def test_validate_v2_notifications_icn_redaction_unexpected_format(
    notify_api,
    mocker,
    recipient_identifier_value,
):
    """
    When POST data validation fails for a Notification, the request body
    should be logged with personalized information redacted.
    """
    mock_logger = mocker.patch('app.schema_validation.current_app.logger.info')
    with pytest.raises(ValidationError):
        validate({'recipient_identifier': recipient_identifier_value}, post_sms_request)

    # Cannot use a variable with loggers and assertions, falsely passes assertions
    mock_logger.assert_called_once_with('Validation failed for: %s', {'recipient_identifier': '<redacted>'})


def test_validate_v2_notifications_icn_and_personalisation_redaction(
    notify_api,
    mocker,
):
    """
    When POST data validation fails for a Notification, the request body
    should be logged with personalized information redacted.
    """
    mock_logger = mocker.patch('app.schema_validation.current_app.logger.info')
    with pytest.raises(ValidationError):
        validate(
            {'recipient_identifier': {'id_type': 'ICN', 'id_value': '1234567890'}, 'personalisation': 'asdf'},
            post_sms_request,
        )

    # Cannot use a variable with loggers and assertions, falsely passes assertions
    mock_logger.assert_called_once_with(
        'Validation failed for: %s',
        {'recipient_identifier': {'id_type': 'ICN', 'id_value': '<redacted>'}, 'personalisation': '<redacted>'},
    )


def test_validate_with_personalisation_files(
    notify_api,
    mocker,
):
    """
    When the call to decode_personalisation_files fails, a ValidationError should be raised.
    """
    # patch the call to decode_personalisation_files
    mocker.patch('app.schema_validation.decode_personalisation_files', return_value=({}, ['error']))

    payload = {
        'personalisation': {'file': 'foo'},
    }
    with pytest.raises(ValidationError):
        validate(payload, {})


@pytest.mark.parametrize(
    'payload',
    [
        'not a dictionary',
        12345,
        ['a', 'list'],
        None,
        '',
        False,
    ],
)
def test_validate_with_invalid_dict(
    notify_api,
    mocker,
    payload,
):
    """
    When the payload is not a dictionary, a ValidationError should be raised.
    """
    with pytest.raises(ValidationError):
        validate(payload, {})

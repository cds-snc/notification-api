from decimal import Decimal

import pytest

from app.integrations.comp_and_pen.scheduled_message_helpers import CompPenMsgHelper
from app.models import SMS_TYPE
from app.va.identifier import IdentifierType


@pytest.fixture
def msg_helper(mocker, dynamodb_mock) -> CompPenMsgHelper:
    # Mocks necessary for dynamodb
    mocker.patch('boto3.resource')
    helper = CompPenMsgHelper('test')
    mocker.patch.object(helper, 'dynamodb_table', dynamodb_mock)
    return helper


def test_ut_get_dynamodb_comp_pen_messages_with_empty_table(msg_helper):
    # Invoke the function with the mocked table and application
    messages = msg_helper.get_dynamodb_comp_pen_messages(message_limit=1)

    assert messages == [], 'Expected no messages from an empty table'


def test_get_dynamodb_comp_pen_messages_filters(msg_helper, sample_dynamodb_insert):
    """
    Items should not be returned if any of the following conditions are met:
        1) is_processed is absent (not on is-processed-index)
        2) paymentAmount is absent (required by downstream Celery task)
    """
    # Insert mock data into the DynamoDB table.
    items_to_insert = [
        # The first 3 items are valid.
        {'participant_id': 1, 'is_processed': 'F', 'payment_id': 1, 'paymentAmount': Decimal(1.00), 'vaprofile_id': 1},
        {'participant_id': 2, 'is_processed': 'F', 'payment_id': 2, 'paymentAmount': Decimal(2.50), 'vaprofile_id': 2},
        {'participant_id': 3, 'is_processed': 'F', 'payment_id': 3, 'paymentAmount': Decimal('3.9'), 'vaprofile_id': 3},
        # Already processed
        {'participant_id': 4, 'payment_id': 4, 'paymentAmount': Decimal(0), 'vaprofile_id': 4},
        # Missing paymentAmount
        {'participant_id': 5, 'is_processed': 'F', 'payment_id': 5, 'vaprofile_id': 5},
    ]
    sample_dynamodb_insert(items_to_insert)

    # Invoke the function with the mocked table and application
    messages = msg_helper.get_dynamodb_comp_pen_messages(message_limit=7)

    for msg in messages:
        assert (
            str(msg['participant_id']) in '123'
        ), f"The message with ID {msg['participant_id']} should have been filtered out."
    assert len(messages) == 3


def test_it_get_dynamodb_comp_pen_messages_with_multiple_scans(msg_helper, sample_dynamodb_insert):
    """
    Items should be searched based on the is-processed-index and anything missing a paymentAmount should be filtered out.

    This is also testing the pagination of the scan operation in which a bug previously existed.
    """
    items_to_insert = (
        # items with is_processed = 'F'
        {
            'participant_id': x,
            'is_processed': 'F',
            'payment_id': x,
            'paymentAmount': Decimal(x * 2.50),
            'vaprofile_id': x * 10,
        }
        if x % 2 == 0
        # items with is_processed removed (not in index)
        else {
            'participant_id': x,
            'payment_id': x,
            'paymentAmount': Decimal(x * 2.50),
            'vaprofile_id': x * 10,
        }
        for x in range(0, 250)
    )

    # Insert mock data into the DynamoDB table.
    sample_dynamodb_insert(items_to_insert)

    # Invoke the function with the mocked table and application
    messages = msg_helper.get_dynamodb_comp_pen_messages(message_limit=100)

    assert len(messages) == 100

    # ensure we only have messages that have not been processed
    for m in messages:
        assert m['is_processed'] == 'F'
        assert m['paymentAmount'] is not None


def test_it_update_dynamo_item_is_processed_updates_properly(
    notify_api, mocker, msg_helper, dynamodb_mock, sample_dynamodb_insert
):
    """Ensure that the 'is_processed' key is removed from the items in the list and the DynamoDB table is updated."""

    items_to_insert = [
        {'participant_id': 1, 'is_processed': 'F', 'payment_id': 1, 'paymentAmount': Decimal(1.00)},
        {'participant_id': 2, 'is_processed': 'F', 'payment_id': 2, 'paymentAmount': Decimal(2.50)},
        {'participant_id': 3, 'payment_id': 1, 'paymentAmount': Decimal(0.00)},
        {'participant_id': 4, 'is_processed': 'F', 'payment_id': 2, 'paymentAmount': Decimal(4.50)},
        {'participant_id': 5, 'is_processed': 'F', 'payment_id': 1, 'paymentAmount': Decimal(5.50)},
    ]

    # Insert mock data into the DynamoDB table.
    sample_dynamodb_insert(items_to_insert)

    mock_logger = mocker.patch('app.integrations.comp_and_pen.scheduled_message_helpers.current_app.logger')

    # why is this giving this error? "RuntimeError: Working outside of application context."
    msg_helper.remove_dynamo_item_is_processed(items_to_insert)

    assert mock_logger.debug.call_count == 5

    response = dynamodb_mock.scan()

    # Ensure we get all 5 records back and they are set with is_processed removed
    assert response['Count'] == 5
    for item in response['Items']:
        assert 'is_processed' not in item


def test_ut_send_scheduled_comp_and_pen_sms_calls_send_notification_with_recipient_item(
    mocker, msg_helper, dynamodb_mock, sample_service, sample_template
):
    # Set up test data
    dynamo_data = [
        {
            'participant_id': '123',
            'vaprofile_id': '123',
            'payment_id': '123',
            'paymentAmount': 123.05,  # Named by Kafka
            'is_processed': False,
        },
    ]

    recipient_item = {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': '123'}

    mocker.patch('app.celery.scheduled_tasks.is_feature_enabled', return_value=True)

    service = sample_service()
    template = sample_template()
    sms_sender_id = str(service.get_default_sms_sender_id())

    mock_send_notification = mocker.patch(
        'app.integrations.comp_and_pen.scheduled_message_helpers.send_notification_bypass_route'
    )

    msg_helper.send_comp_and_pen_sms(
        service=service,
        template=template,
        sms_sender_id=sms_sender_id,
        comp_and_pen_messages=dynamo_data,
        perf_to_number=None,
    )

    # Assert the expected information is passed to "send_notification_bypass_route"
    mock_send_notification.assert_called_once_with(
        service=service,
        template=template,
        notification_type=SMS_TYPE,
        personalisation={'amount': '123.05'},
        sms_sender_id=sms_sender_id,
        recipient=None,
        recipient_item=recipient_item,
    )


@pytest.mark.parametrize(
    'amount, formatted_amount',
    [
        (1123.05, '1,123.05'),
        (1000.00, '1,000.00'),
        (10000.00, '10,000.00'),
        (1234567.89, '1,234,567.89'),
        (50.5, '50.50'),
        (0.5, '0.50'),
        (0.0, '0.00'),
    ],
)
def test_ut_send_scheduled_comp_and_pen_sms_formatted_amount_correctly(
    mocker, msg_helper, dynamodb_mock, sample_service, sample_template, amount, formatted_amount
):
    dynamo_data = [
        {
            'participant_id': '123',
            'vaprofile_id': '123',
            'payment_id': '123',
            'paymentAmount': amount,
            'is_processed': False,
        },
    ]

    recipient_item = {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': '123'}

    mocker.patch('app.celery.scheduled_tasks.is_feature_enabled', return_value=True)

    service = sample_service()
    template = sample_template()
    sms_sender_id = str(service.get_default_sms_sender_id())

    mock_send_notification = mocker.patch(
        'app.integrations.comp_and_pen.scheduled_message_helpers.send_notification_bypass_route'
    )

    msg_helper.send_comp_and_pen_sms(
        service=service,
        template=template,
        sms_sender_id=sms_sender_id,
        comp_and_pen_messages=dynamo_data,
        perf_to_number=None,
    )

    mock_send_notification.assert_called_once_with(
        service=service,
        template=template,
        notification_type=SMS_TYPE,
        personalisation={'amount': formatted_amount},
        sms_sender_id=sms_sender_id,
        recipient=None,
        recipient_item=recipient_item,
    )


def test_ut_send_scheduled_comp_and_pen_sms_payment_amount_key_does_not_exist(
    mocker,
    msg_helper,
    dynamodb_mock,
    sample_service,
    sample_template,
):
    dynamo_data = [
        {
            'participant_id': '123',
            'vaprofile_id': '123',
            'payment_id': '123',
            'is_processed': False,
        },
    ]

    recipient_item = {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': '123'}

    mocker.patch('app.celery.scheduled_tasks.is_feature_enabled', return_value=True)

    service = sample_service()
    template = sample_template()
    sms_sender_id = str(service.get_default_sms_sender_id())

    mock_send_notification = mocker.patch(
        'app.integrations.comp_and_pen.scheduled_message_helpers.send_notification_bypass_route'
    )

    msg_helper.send_comp_and_pen_sms(
        service=service,
        template=template,
        sms_sender_id=sms_sender_id,
        comp_and_pen_messages=dynamo_data,
        perf_to_number=None,
    )

    mock_send_notification.assert_called_once_with(
        service=service,
        template=template,
        notification_type=SMS_TYPE,
        personalisation={'amount': '0.00'},
        sms_sender_id=sms_sender_id,
        recipient=None,
        recipient_item=recipient_item,
    )

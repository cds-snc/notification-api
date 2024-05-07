import pytest
from app.exceptions import NotificationTechnicalFailureException
from app.models import SMS_TYPE, EMAIL_TYPE, KEY_TYPE_NORMAL
from app.notifications.send_notifications import send_notification_bypass_route
from app.va.identifier import IdentifierType


def test_send_notification_bypass_route_no_recipient(
    mocker,
    sample_template,
):
    template = sample_template()
    persist_notification_mock = mocker.patch('app.notifications.send_notifications.persist_notification')
    mock_logger = mocker.patch('app.notifications.send_notifications.current_app.logger.critical')

    # Test the case where recipient and recipient_item are None, should log critical error.
    with pytest.raises(NotificationTechnicalFailureException):
        send_notification_bypass_route(template.service, template, SMS_TYPE, recipient=None, recipient_item=None)

    persist_notification_mock.assert_not_called()
    mock_logger.assert_called_once()


##################################################
# sms tests
##################################################
def test_send_notification_bypass_route_sms_with_recipient_and_default_sms_sender(
    mocker,
    sample_notification,
):
    notification = sample_notification()
    template = notification.template
    service = notification.template.service

    persist_notification_mock = mocker.patch(
        'app.notifications.send_notifications.persist_notification', return_value=notification
    )
    send_notification_to_queue_mock = mocker.patch('app.notifications.send_notifications.send_notification_to_queue')

    # Test sending an SMS notification using the default sms_sender_id when it's not provided
    send_notification_bypass_route(
        service=service,
        template=template,
        notification_type=SMS_TYPE,
        recipient='+11234567890',
    )

    default_sms_sender = service.get_default_sms_sender_id()

    # Assert that the default SMS sender ID was used
    persist_notification_mock.assert_called_with(
        template_id=template.id,
        template_version=template.version,
        recipient='+11234567890',
        service_id=service.id,
        personalisation=None,
        notification_type=SMS_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        recipient_identifier=None,
        sms_sender_id=default_sms_sender,
    )

    # Assert that the notification was queued correctly
    send_notification_to_queue_mock.assert_called_with(
        notification=notification,
        research_mode=False,
        queue=None,
        recipient_id_type=None,
        sms_sender_id=default_sms_sender,
    )


def test_send_notification_bypass_route_sms_with_recipient_item(
    mocker,
    sample_notification,
):
    notification = sample_notification()
    template = notification.template
    service = notification.template.service

    persist_notification_mock = mocker.patch(
        'app.notifications.send_notifications.persist_notification', return_value=notification
    )
    send_to_queue_for_recipient_info_based_on_recipient_identifier_mock = mocker.patch(
        'app.notifications.send_notifications.send_to_queue_for_recipient_info_based_on_recipient_identifier'
    )

    recipient_item = {'id_type': 'VAPROFILEID', 'id_value': '1234'}

    # Test sending an SMS notification using the recipient_item
    send_notification_bypass_route(
        service=service,
        template=template,
        notification_type=SMS_TYPE,
        recipient_item=recipient_item,
        sms_sender_id='test_sms_sender',
    )

    # Assert the notification received the expected params
    persist_notification_mock.assert_called_with(
        template_id=template.id,
        template_version=template.version,
        recipient=None,
        service_id=service.id,
        personalisation=None,
        notification_type=SMS_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        recipient_identifier=recipient_item,
        sms_sender_id='test_sms_sender',
    )

    # Assert that the notification was queued correctly, with expected params
    send_to_queue_for_recipient_info_based_on_recipient_identifier_mock.assert_called_with(
        notification=notification,
        id_type=recipient_item['id_type'],
        id_value=recipient_item['id_value'],
        communication_item_id=template.communication_item_id,
        onsite_enabled=False,
    )


##################################################
# email tests
##################################################
def test_send_notification_bypass_route_email_with_recipient(
    mocker,
    sample_notification,
):
    notification = sample_notification(gen_type=EMAIL_TYPE)
    template = notification.template
    service = template.service

    persist_notification_mock = mocker.patch(
        'app.notifications.send_notifications.persist_notification', return_value=notification
    )
    send_notification_to_queue_mock = mocker.patch('app.notifications.send_notifications.send_notification_to_queue')

    # Test sending an email notification with recipient
    send_notification_bypass_route(
        service=service,
        template=template,
        notification_type=EMAIL_TYPE,
        recipient='test123@email.com',
    )

    # Assert the notification received the expected params
    persist_notification_mock.assert_called_with(
        template_id=template.id,
        template_version=template.version,
        recipient='test123@email.com',
        service_id=service.id,
        personalisation=None,
        notification_type=EMAIL_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        recipient_identifier=None,
        sms_sender_id=None,
    )

    # Assert the notification was queued correctly, with expected params
    send_notification_to_queue_mock.assert_called_with(
        notification=notification,
        research_mode=False,
        queue=None,
        recipient_id_type=None,
        sms_sender_id=None,
    )


def test_send_notification_bypass_route_email_with_recipient_item(
    mocker,
    sample_notification,
):
    notification = sample_notification(gen_type=EMAIL_TYPE)
    template = notification.template
    service = template.service

    persist_notification_mock = mocker.patch(
        'app.notifications.send_notifications.persist_notification', return_value=notification
    )
    send_to_queue_for_recipient_info_based_on_recipient_identifier_mock = mocker.patch(
        'app.notifications.send_notifications.send_to_queue_for_recipient_info_based_on_recipient_identifier'
    )
    recipient_item = {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': '1234'}

    # Test sending an email notification, with recipient_item
    send_notification_bypass_route(
        service=service,
        template=template,
        notification_type=EMAIL_TYPE,
        recipient_item=recipient_item,
    )

    # Assert the notification received the expected params
    persist_notification_mock.assert_called_with(
        template_id=template.id,
        template_version=template.version,
        recipient=None,
        service_id=service.id,
        personalisation=None,
        notification_type=EMAIL_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        recipient_identifier=recipient_item,
        sms_sender_id=None,
    )

    # Assert that the notification was queued correctly, with the expected params
    send_to_queue_for_recipient_info_based_on_recipient_identifier_mock.assert_called_with(
        notification=notification,
        id_type=recipient_item['id_type'],
        id_value=recipient_item['id_value'],
        communication_item_id=template.communication_item_id,
        onsite_enabled=False,
    )

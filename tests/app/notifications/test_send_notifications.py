import pytest
from sqlalchemy.orm.exc import NoResultFound

from app.constants import EMAIL_TYPE, KEY_TYPE_NORMAL, SMS_TYPE
from app.exceptions import NotificationTechnicalFailureException
from app.models import Service, Template
from app.notifications.send_notifications import lookup_notification_sms_setup_data, send_notification_bypass_route
from app.va.identifier import IdentifierType


@pytest.mark.parametrize('sms_sender_id', ('This is not a UUID.', 'd1abbb27-9c72-4de4-8463-dbdf24d3fdd6'))
def test_ut_lookup_notification_sms_setup_data_sms_sender_selection(
    notify_api,
    mocker,
    sms_sender_id,
):
    service_id = 'service_id'
    template_id = 'template_id'
    sms_sender_id = sms_sender_id

    service = Service()
    template = Template()

    mock_fetch_service = mocker.patch(
        'app.notifications.send_notifications.dao_fetch_service_by_id', return_value=service
    )
    mock_get_template = mocker.patch(
        'app.notifications.send_notifications.dao_get_template_by_id', return_value=template
    )
    mock_get_default_sms_sender_id = mocker.patch(
        'app.notifications.send_notifications.Service.get_default_sms_sender_id', return_value='sms-sender-id'
    )

    result = lookup_notification_sms_setup_data(service_id, template_id, sms_sender_id)

    mock_fetch_service.assert_called_once_with(service_id)
    mock_get_template.assert_called_once_with(template_id)

    if 'This is not a UUID.' in sms_sender_id:
        assert result == (service, template, mock_get_default_sms_sender_id.return_value)
    else:
        assert result == (service, template, sms_sender_id)


def test_ut_lookup_notification_sms_setup_data_no_result_found(notify_api, mocker):
    service_id = 'service_id'
    template_id = 'template_id'
    sms_sender_id = 'not used in this test'

    dao_fetch_service_by_id_mock = mocker.patch(
        'app.notifications.send_notifications.dao_fetch_service_by_id', side_effect=(service_id, NoResultFound)
    )
    dao_get_template_by_id_mock = mocker.patch(
        'app.notifications.send_notifications.dao_get_template_by_id', side_effect=(NoResultFound, template_id)
    )

    mock_logger = mocker.patch('app.notifications.send_notifications.current_app.logger')

    with pytest.raises(NoResultFound):
        lookup_notification_sms_setup_data(service_id, template_id, sms_sender_id)

    dao_fetch_service_by_id_mock.assert_called_once_with(service_id)
    dao_get_template_by_id_mock.assert_called_once_with(template_id)
    mock_logger.exception.assert_called_once()


def test_send_notification_bypass_route_no_recipient(
    mocker,
    sample_template,
):
    template: Template = sample_template()
    service: Service = template.service
    persist_notification_mock = mocker.patch('app.notifications.send_notifications.persist_notification')
    mock_logger = mocker.patch('app.notifications.send_notifications.current_app.logger.critical')

    # Test the case where recipient and recipient_item are None, should log critical error.
    with pytest.raises(NotificationTechnicalFailureException):
        send_notification_bypass_route(
            service,
            template,
            SMS_TYPE,
            reply_to_text=service.get_default_sms_sender(),
            recipient=None,
            recipient_item=None,
        )

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
    service: Service = notification.template.service
    sender_number = service.get_default_sms_sender()

    persist_notification_mock = mocker.patch(
        'app.notifications.send_notifications.persist_notification', return_value=notification
    )
    send_notification_to_queue_mock = mocker.patch('app.notifications.send_notifications.send_notification_to_queue')

    # Test sending an SMS notification using the default sms_sender_id when it's not provided
    send_notification_bypass_route(
        service=service,
        template=template,
        notification_type=SMS_TYPE,
        reply_to_text=sender_number,
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
        reply_to_text=sender_number,
        notification_id=None,
    )

    # Assert that the notification was queued correctly
    send_notification_to_queue_mock.assert_called_with(
        notification=notification,
        research_mode=False,
        sms_sender_id=default_sms_sender,
    )


def test_send_notification_bypass_route_sms_with_recipient_item(
    mocker,
    sample_notification,
):
    notification = sample_notification()
    template = notification.template
    service: Service = notification.template.service
    sender_number = service.get_default_sms_sender()

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
        reply_to_text=sender_number,
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
        reply_to_text=sender_number,
        notification_id=None,
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
    service: Service = template.service
    send_number = service.get_default_sms_sender()

    persist_notification_mock = mocker.patch(
        'app.notifications.send_notifications.persist_notification', return_value=notification
    )
    send_notification_to_queue_mock = mocker.patch('app.notifications.send_notifications.send_notification_to_queue')

    # Test sending an email notification with recipient
    send_notification_bypass_route(
        service=service,
        template=template,
        reply_to_text=send_number,
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
        reply_to_text=send_number,
        notification_id=None,
    )

    # Assert the notification was queued correctly, with expected params
    send_notification_to_queue_mock.assert_called_with(
        notification=notification,
        research_mode=False,
        sms_sender_id=None,
    )


def test_send_notification_bypass_route_email_with_recipient_item(
    mocker,
    sample_notification,
):
    notification = sample_notification(gen_type=EMAIL_TYPE)
    template: Template = notification.template
    service: Service = template.service
    reply_to = template.get_reply_to_text()

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
        reply_to_text=reply_to,
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
        reply_to_text=reply_to,
        notification_id=None,
    )

    # Assert that the notification was queued correctly, with the expected params
    send_to_queue_for_recipient_info_based_on_recipient_identifier_mock.assert_called_with(
        notification=notification,
        id_type=recipient_item['id_type'],
        id_value=recipient_item['id_value'],
        communication_item_id=template.communication_item_id,
        onsite_enabled=False,
    )

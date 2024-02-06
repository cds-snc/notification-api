import pytest
from app.celery.v3.notification_tasks import (
    v3_create_notification_instance,
    v3_process_notification,
    v3_send_email_notification,
    v3_send_sms_notification,
)
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    Notification,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    NotificationFailures,
    SMS_TYPE,
    TemplateHistory,
)
from sqlalchemy import select
from uuid import uuid4


############################################################################################
# Test non-schema validations.
############################################################################################


def test_v3_process_notification_no_template(notify_db_session, mocker, sample_service):
    """
    Call the task with request data referencing a nonexistent template.
    """

    request_data = {
        'id': str(uuid4()),
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': '22222222-2222-2222-2222-222222222222',
    }

    v3_send_email_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_email_notification.delay')
    v3_process_notification(request_data, sample_service().id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_not_called()

    notification_failure = notify_db_session.session.get(NotificationFailures, request_data['id'])

    try:
        assert notification_failure.body['status'] == NOTIFICATION_PERMANENT_FAILURE
        assert notification_failure.body['status_reason'] == 'The template does not exist.'
        assert notification_failure.body['phone_number'] is None
        assert notification_failure.body['email_address'] == 'test@va.gov'
    finally:
        notify_db_session.session.delete(notification_failure)
        notify_db_session.session.commit()


def test_v3_process_notification_template_owner_mismatch(
    notify_db_session, mocker, sample_service, sample_template
):
    """
    Call the task with request data for a template the service doesn't own.
    """

    service1 = sample_service()
    service2 = sample_service()
    assert service1.id != service2.id
    template = sample_template(service=service2)
    assert template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': template.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, service1.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    notification_failure = notify_db_session.session.get(NotificationFailures, request_data['id'])

    try:
        assert notification_failure.body['status'] == NOTIFICATION_PERMANENT_FAILURE
        assert notification_failure.body['status_reason'] == 'The service does not own the template.'
    finally:
        notify_db_session.session.delete(notification_failure)
        notify_db_session.session.commit()


def test_v3_process_notification_template_type_mismatch_1(notify_db_session, mocker, sample_service, sample_template):
    """
    Call the task with request data for an e-mail notification, but specify an SMS template.
    """

    service = sample_service()
    template = sample_template(service=service)
    assert template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': template.id,
    }

    v3_send_email_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_email_notification.delay')
    v3_process_notification(request_data, service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_not_called()

    notification_failure = notify_db_session.session.get(NotificationFailures, request_data['id'])

    try:
        assert notification_failure.body['status'] == NOTIFICATION_PERMANENT_FAILURE
        assert notification_failure.body['status_reason'] == 'The template type does not match the notification type.'
    finally:
        notify_db_session.session.delete(notification_failure)
        notify_db_session.session.commit()


def test_v3_process_notification_template_type_mismatch_2(notify_db_session, mocker, sample_service, sample_template):
    """
    Call the task with request data for an SMS notification, but specify an e-mail template.
    """

    service = sample_service()
    template = sample_template(service=service, template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': template.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    notification_failure = notify_db_session.session.get(NotificationFailures, request_data['id'])

    try:
        assert notification_failure.body['status'] == NOTIFICATION_PERMANENT_FAILURE
        assert notification_failure.body['status_reason'] == 'The template type does not match the notification type.'
    finally:
        notify_db_session.session.delete(notification_failure)
        notify_db_session.session.commit()


############################################################################################
# Test sending e-mail notifications.
############################################################################################


def test_v3_process_notification_valid_email(notify_db_session, mocker, sample_service, sample_template):
    """
    Given data for a valid e-mail notification, the task v3_process_notification should pass a Notification
    instance to the task v3_send_email_notification.
    """

    service = sample_service()
    template = sample_template(service=service, template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': template.id,
    }

    v3_send_email_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_email_notification.delay')
    v3_process_notification(request_data, service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_called_once()
    assert isinstance(v3_send_email_notification_mock.call_args.args[0], Notification)


@pytest.mark.xfail(reason='#1634')
def test_v3_send_email_notification(mocker, notify_db_session, sample_template):
    """
    Given a valid, not-persisted Notification instance, the task v3_send_email_notification should
    call "send_email" using a provider client.
    """

    template = sample_template(template_type=EMAIL_TYPE)
    assert notify_db_session.session.get(TemplateHistory, (template.id, template.version)) is not None, \
        'Needed downstream to avoid IntegrityError.'

    client_mock = mocker.Mock()
    client_mock.send_email = mocker.Mock(return_value='provider reference')
    client_mock.get_name = mocker.Mock(return_value='client name')
    mocker.patch('app.celery.v3.notification_tasks.clients.get_email_client', return_value=client_mock)

    request_data = {
        'id': str(uuid4()),
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': template.id,
    }

    notification = v3_create_notification_instance(
        request_data,
        template.service_id,
        None,
        KEY_TYPE_TEST,
        template.version,
    )
    assert notification.notification_type == EMAIL_TYPE
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE

    v3_send_email_notification(notification, template)
    client_mock.send_email.assert_called_once()

    stmt = select(Notification).where(Notification.service_id == template.service_id)
    notification_from_db = notify_db_session.session.scalars(stmt).one()

    try:
        assert notification_from_db.status == NOTIFICATION_SENT
        assert notification_from_db.reference == 'provider reference'
        assert notification_from_db.sent_by == 'client name'
    finally:
        notify_db_session.session.delete(notification_from_db)
        notify_db_session.session.commit()


############################################################################################
# Test sending SMS notifications.
############################################################################################


def test_v3_process_notification_valid_sms_with_sender_id(
    notify_db_session, mocker, sample_service, sample_template, sample_sms_sender
):
    """
    Given data for a valid SMS notification that includes an sms_sender_id, the task v3_process_notification
    should pass a Notification instance to the task v3_send_sms_notification.
    """

    service = sample_service()
    template = sample_template(service=service)
    assert template.template_type == SMS_TYPE
    sms_sender = sample_sms_sender(service.id)

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': template.id,
        'sms_sender_id': sms_sender.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_called_once_with(mocker.ANY, sms_sender.sms_sender)
    assert isinstance(v3_send_sms_notification_mock.call_args.args[0], Notification)


def test_v3_process_notification_valid_sms_without_sender_id(
    notify_db_session, mocker, sample_service, sample_template, sample_sms_sender
):
    """
    Given data for a valid SMS notification that does not include an sms_sender_id, the task v3_process_notification
    should pass a Notification instance to the task v3_send_sms_notification.
    """

    service = sample_service()
    template = sample_template(service=service)
    assert template.template_type == SMS_TYPE
    sms_sender = sample_sms_sender(service.id)

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': template.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')

    get_default_sms_sender_id_mock = mocker.patch(
        'app.celery.v3.notification_tasks.get_default_sms_sender_id', return_value=(None, sms_sender.id)
    )

    v3_process_notification(request_data, service.id, None, KEY_TYPE_TEST)

    v3_send_sms_notification_mock.assert_called_once_with(mocker.ANY, sms_sender.sms_sender)

    _notification = v3_send_sms_notification_mock.call_args.args[0]
    assert isinstance(_notification, Notification)
    _err, _sender_id = get_default_sms_sender_id_mock.return_value
    assert _err is None
    assert _notification.sms_sender_id == _sender_id

    get_default_sms_sender_id_mock.assert_called_once_with(service.id)


def test_v3_process_notification_valid_sms_with_invalid_sender_id(
    notify_db_session, mocker, sample_service, sample_template
):
    """
    Given data for a valid SMS notification that includes an INVALID sms_sender_id,
    v3_process_notification should NOT call v3_send_sms_notification after checking sms_sender_id.
    """

    service = sample_service()
    template = sample_template(service=service)
    assert template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': template.id,
        'sms_sender_id': '111a1111-aaaa-1aa1-aa11-a1111aa1a1a1',
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    notification_failure = notify_db_session.session.get(NotificationFailures, request_data['id'])

    try:
        assert notification_failure.body['status'] == NOTIFICATION_PERMANENT_FAILURE
        assert notification_failure.body['status_reason'] == 'SMS sender does not exist.'
    finally:
        notify_db_session.session.delete(notification_failure)
        notify_db_session.session.commit()


def test_v3_send_sms_notification(mocker, notify_db_session, sample_service, sample_template, sample_sms_sender):
    """
    Given a valid, not-persisted Notification instance, the task v3_send_sms_notification should
    call "send_email" using a provider client.
    """

    template = sample_template()
    assert template.template_type == SMS_TYPE
    assert notify_db_session.session.get(TemplateHistory, (template.id, template.version)) is not None, \
        'Needed downstream to avoid IntegrityError.'

    service = sample_service()
    sms_sender = sample_sms_sender(service.id)

    client_mock = mocker.Mock()
    client_mock.send_sms = mocker.Mock(return_value='provider reference')
    client_mock.get_name = mocker.Mock(return_value='client name')
    mocker.patch('app.celery.v3.notification_tasks.clients.get_sms_client', return_value=client_mock)

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': template.id,
        'sms_sender_id': sms_sender.id,
    }

    notification = v3_create_notification_instance(
        request_data,
        template.service_id,
        None,
        KEY_TYPE_TEST,
        template.version,
    )
    assert notification.notification_type == SMS_TYPE
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE

    v3_send_sms_notification(notification, sms_sender.sms_sender)

    stmt = select(Notification).where(Notification.service_id == template.service_id)
    notification_from_db = notify_db_session.session.scalars(stmt).one()

    client_mock.send_sms.assert_called_once_with(
        notification_from_db.to,
        notification_from_db.content,
        notification_from_db.client_reference,
        True,
        sms_sender.sms_sender
    )

    try:
        assert notification_from_db.status == NOTIFICATION_SENT
        assert notification_from_db.reference == 'provider reference'
        assert notification_from_db.sent_by == 'client name'
    finally:
        notify_db_session.session.delete(notification_from_db)
        notify_db_session.session.commit()


def test_v3_process_sms_notification_with_non_existent_template(
    notify_db_session, mocker, sample_service, sample_template
):
    """
    Call the task with request data for non-existent template.
    """

    assert sample_template().template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': '11111111-1111-1111-1111-111111111111',
        'sms_sender_id': '11111111-1111-1111-1111-111111111111',
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, sample_service().id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    notification_failure = notify_db_session.session.get(NotificationFailures, request_data['id'])

    try:
        assert notification_failure.body['status'] == NOTIFICATION_PERMANENT_FAILURE
        assert notification_failure.body['status_reason'] == 'The template does not exist.'
        assert notification_failure.body['phone_number'] == '+18006982411'
        assert notification_failure.body['email_address'] is None
    finally:
        notify_db_session.session.delete(notification_failure)
        notify_db_session.session.commit()

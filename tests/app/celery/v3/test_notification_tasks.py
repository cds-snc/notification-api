from app.celery.v3.notification_tasks import (
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
    Template,
    SMS_TYPE,
)
from sqlalchemy import select
from uuid import uuid4


############################################################################################
# Test non-schema validations.
############################################################################################


# TODO - Make the Notification.template_id field nullable?  Have a default template?
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
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_not_called()

    query = select(NotificationFailures).where(NotificationFailures.notification_id == request_data['id'])
    notification_failure = notify_db_session.session.execute(query).one()[0]
    body = notification_failure.body

    assert body.get('status') == NOTIFICATION_PERMANENT_FAILURE
    assert body.get('status_reason') == 'The template does not exist.'
    assert body.get('phone_number') is None
    assert body.get('email_address') == 'test@va.gov'


def test_v3_process_notification_template_owner_mismatch(
    notify_db_session, mocker, sample_service, sample_template, other_sample_template
):
    """
    Call the task with request data for a template the service doesn't own.
    """
    assert sample_template.template_type == SMS_TYPE
    assert sample_template.service_id == sample_service.id

    assert other_sample_template.template_type == SMS_TYPE
    assert other_sample_template.service_id != sample_service.id

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': other_sample_template.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    query = select(NotificationFailures).where(NotificationFailures.notification_id == request_data['id'])
    notification_failure = notify_db_session.session.execute(query).one()[0]
    body = notification_failure.body

    assert body.get('status') == NOTIFICATION_PERMANENT_FAILURE
    assert body.get('status_reason') == 'The service does not own the template.'


def test_v3_process_notification_template_type_mismatch_1(notify_db_session, mocker, sample_service, sample_template):
    """
    Call the task with request data for an e-mail notification, but specify an SMS template.
    """

    assert sample_template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': sample_template.id,
    }

    v3_send_email_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_email_notification.delay')
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_not_called()

    query = select(NotificationFailures).where(NotificationFailures.notification_id == request_data['id'])
    notification_failure = notify_db_session.session.execute(query).one()[0]
    body = notification_failure.body

    assert body.get('status') == NOTIFICATION_PERMANENT_FAILURE
    assert body.get('status_reason') == 'The template type does not match the notification type.'
    assert body.get('phone_number') is None
    assert body.get('email_address') == 'test@va.gov'


def test_v3_process_notification_template_type_mismatch_2(
    notify_db_session, mocker, sample_service, sample_email_template
):
    """
    Call the task with request data for an SMS notification, but specify an e-mail template.
    """

    assert sample_email_template.template_type == EMAIL_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': sample_email_template.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    query = select(NotificationFailures).where(NotificationFailures.notification_id == request_data['id'])
    notification_failure = notify_db_session.session.execute(query).one()[0]
    body = notification_failure.body

    assert body.get('status') == NOTIFICATION_PERMANENT_FAILURE
    assert body.get('status_reason') == 'The template type does not match the notification type.'


############################################################################################
# Test sending e-mail notifications.
############################################################################################


def test_v3_process_notification_valid_email(notify_db_session, mocker, sample_service, sample_email_template):
    """
    Given data for a valid e-mail notification, the task v3_process_notification should pass a Notification
    instance to the task v3_send_email_notification.
    """

    assert sample_email_template.template_type == EMAIL_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': EMAIL_TYPE,
        'email_address': 'test@va.gov',
        'template_id': sample_email_template.id,
    }

    v3_send_email_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_email_notification.delay')
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_called_once()
    assert isinstance(v3_send_email_notification_mock.call_args.args[0], Notification)


def test_v3_send_email_notification(notify_db_session, mocker, sample_email_notification):
    assert sample_email_notification.notification_type == EMAIL_TYPE

    client_mock = mocker.Mock()
    client_mock.send_email = mocker.Mock(return_value='provider reference')
    client_mock.get_name = mocker.Mock(return_value='client name')
    mocker.patch('app.celery.v3.notification_tasks.clients.get_email_client', return_value=client_mock)

    query = select(Template).where(Template.id == sample_email_notification.template_id)
    template = notify_db_session.session.execute(query).one().Template

    v3_send_email_notification(sample_email_notification, template)
    client_mock.send_email.assert_called_once()  # TODO

    query = select(Notification).where(Notification.id == sample_email_notification.id)
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_SENT
    assert notification.reference == 'provider reference'
    assert notification.sent_by == 'client name'


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

    assert sample_template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': sample_template.id,
        'sms_sender_id': sample_sms_sender.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_called_once_with(mocker.ANY, sample_sms_sender.sms_sender)
    assert isinstance(v3_send_sms_notification_mock.call_args.args[0], Notification)


def test_v3_process_notification_valid_sms_without_sender_id(
    notify_db_session, mocker, sample_service, sample_template, sample_sms_sender
):
    """
    Given data for a valid SMS notification that does not include an sms_sender_id, the task v3_process_notification
    should pass a Notification instance to the task v3_send_sms_notification.
    """

    assert sample_template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': sample_template.id,
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')

    get_default_sms_sender_id_mock = mocker.patch(
        'app.celery.v3.notification_tasks.get_default_sms_sender_id', return_value=(None, sample_sms_sender.id)
    )

    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)

    v3_send_sms_notification_mock.assert_called_once_with(mocker.ANY, sample_sms_sender.sms_sender)

    _notification = v3_send_sms_notification_mock.call_args.args[0]
    assert isinstance(_notification, Notification)
    _err, _sender_id = get_default_sms_sender_id_mock.return_value
    assert _err is None
    assert _notification.sms_sender_id == _sender_id

    get_default_sms_sender_id_mock.assert_called_once_with(sample_service.id)


def test_v3_process_notification_valid_sms_with_invalid_sender_id(
    notify_db_session, mocker, sample_service, sample_template, sample_sms_sender
):
    """
    Given data for a valid SMS notification that includes an INVALID sms_sender_id,
    v3_process_notification should NOT call v3_send_sms_notification after checking sms_sender_id.
    """

    assert sample_template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': sample_template.id,
        'sms_sender_id': '11111111-1111-1111-1111-111111111111',
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    query = select(NotificationFailures).where(NotificationFailures.notification_id == request_data['id'])
    notification_failure = notify_db_session.session.execute(query).one()[0]
    body = notification_failure.body

    assert body.get('status') == NOTIFICATION_PERMANENT_FAILURE
    assert body.get('status_reason') == 'SMS sender does not exist.'


def test_v3_send_sms_notification(notify_db_session, mocker, sample_notification, sample_sms_sender):
    assert sample_notification.notification_type == SMS_TYPE

    client_mock = mocker.Mock()
    client_mock.send_sms = mocker.Mock(return_value='provider reference')
    client_mock.get_name = mocker.Mock(return_value='client name')
    mocker.patch('app.celery.v3.notification_tasks.clients.get_sms_client', return_value=client_mock)

    v3_send_sms_notification(sample_notification, sample_sms_sender.sms_sender)
    client_mock.send_sms.assert_called_once_with(
        sample_notification.to,
        sample_notification.content,
        sample_notification.client_reference,
        True,
        sample_sms_sender.sms_sender,
    )

    query = select(Notification).where(Notification.id == sample_notification.id)
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_SENT
    assert notification.reference == 'provider reference'
    assert notification.sent_by == 'client name'


def test_v3_process_sms_notification_with_non_existent_template(
    notify_db_session, mocker, sample_service, sample_template, sample_sms_sender
):
    """
    Call the task with request data for non-existent template.
    """
    assert sample_template.template_type == SMS_TYPE

    request_data = {
        'id': str(uuid4()),
        'notification_type': SMS_TYPE,
        'phone_number': '+18006982411',
        'template_id': '11111111-1111-1111-1111-111111111111',
        'sms_sender_id': '11111111-1111-1111-1111-111111111111',
    }

    v3_send_sms_notification_mock = mocker.patch('app.celery.v3.notification_tasks.v3_send_sms_notification.delay')
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    query = select(NotificationFailures).where(NotificationFailures.notification_id == request_data['id'])
    notification_failure = notify_db_session.session.execute(query).one()[0]
    body = notification_failure.body

    assert body.get('status') == NOTIFICATION_PERMANENT_FAILURE
    assert body.get('status_reason') == 'The template does not exist.'
    assert body.get('phone_number') == '+18006982411'
    assert body.get('email_address') is None

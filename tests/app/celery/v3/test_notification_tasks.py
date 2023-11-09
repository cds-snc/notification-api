import pytest
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
    Template,
    SMS_TYPE,
)
from sqlalchemy import select
from uuid import uuid4


############################################################################################
# Test non-schema validations.
############################################################################################

# TODO - Make the Notification.template_id field nullable?  Have a default template?
@pytest.mark.xfail(reason="A Notification with an invalid template ID cannot be persisted.")
def test_v3_process_notification_no_template(notify_db_session, mocker, sample_service):
    """
    Call the task with request data referencing a nonexistent template.
    """

    request_data = {
        "id": str(uuid4()),
        "notification_type": EMAIL_TYPE,
        "email_address": "test@va.gov",
        "template_id": "4f365dd4-332e-454d-94ff-e393463602db",
    }

    v3_send_email_notification_mock = mocker.patch("app.celery.v3.notification_tasks.v3_send_email_notification.delay")
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_not_called()

    query = select(Notification).where(Notification.id == request_data["id"])
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == "The template does not exist."


@pytest.mark.xfail(reason="This test needs a template not owned by sample_service.", run=False)
def test_v3_process_notification_template_owner_mismatch(
    notify_db_session, mocker, sample_service, sample_template, sample_template_without_email_permission
):
    """
    Call the task with request data for a template the service doesn't own.
    """

    assert sample_template.template_type == SMS_TYPE
    assert sample_template.service_id == sample_service.id

    assert sample_template_without_email_permission.template_type == EMAIL_TYPE
    assert sample_template_without_email_permission.service_id != sample_service.id

    request_data = {
        "id": str(uuid4()),
        "notification_type": SMS_TYPE,
        "phone_number": "+18006982411",
        "template_id": sample_template.id,
    }

    v3_send_sms_notification_mock = mocker.patch("app.celery.v3.notification_tasks.v3_send_sms_notification.delay")
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    query = select(Notification).where(Notification.id == request_data["id"])
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == "The service does not own the template."


def test_v3_process_notification_template_type_mismatch_1(notify_db_session, mocker, sample_service, sample_template):
    """
    Call the task with request data for an e-mail notification, but specify an SMS template.
    """

    assert sample_template.template_type == SMS_TYPE

    request_data = {
        "id": str(uuid4()),
        "notification_type": EMAIL_TYPE,
        "email_address": "test@va.gov",
        "template_id": sample_template.id,
    }

    v3_send_email_notification_mock = mocker.patch("app.celery.v3.notification_tasks.v3_send_email_notification.delay")
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_not_called()

    query = select(Notification).where(Notification.id == request_data["id"])
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == "The template type does not match the notification type."


def test_v3_process_notification_template_type_mismatch_2(
    notify_db_session, mocker, sample_service, sample_email_template
):
    """
    Call the task with request data for an SMS notification, but specify an e-mail template.
    """

    assert sample_email_template.template_type == EMAIL_TYPE

    request_data = {
        "id": str(uuid4()),
        "notification_type": SMS_TYPE,
        "phone_number": "+18006982411",
        "template_id": sample_email_template.id,
    }

    v3_send_sms_notification_mock = mocker.patch("app.celery.v3.notification_tasks.v3_send_sms_notification.delay")
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()

    query = select(Notification).where(Notification.id == request_data["id"])
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert notification.status_reason == "The template type does not match the notification type."


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
        "id": str(uuid4()),
        "notification_type": EMAIL_TYPE,
        "email_address": "test@va.gov",
        "template_id": sample_email_template.id,
    }

    v3_send_email_notification_mock = mocker.patch("app.celery.v3.notification_tasks.v3_send_email_notification.delay")
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_email_notification_mock.assert_called_once()
    assert isinstance(v3_send_email_notification_mock.call_args.args[0], Notification)


def test_v3_send_email_notification(notify_db_session, mocker, sample_email_notification):
    assert sample_email_notification.notification_type == EMAIL_TYPE

    client_mock = mocker.Mock()
    client_mock.send_email = mocker.Mock(return_value="provider reference")
    client_mock.get_name = mocker.Mock(return_value="client name")
    mocker.patch("app.celery.v3.notification_tasks.clients.get_email_client", return_value=client_mock)

    query = select(Template).where(Template.id == sample_email_notification.template_id)
    template = notify_db_session.session.execute(query).one().Template

    v3_send_email_notification(sample_email_notification, template)
    client_mock.send_email.assert_called_once()  # TODO

    query = select(Notification).where(Notification.id == sample_email_notification.id)
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_SENT
    assert notification.reference == "provider reference"
    assert notification.sent_by == "client name"


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
        "id": str(uuid4()),
        "notification_type": SMS_TYPE,
        "phone_number": "+18006982411",
        "template_id": sample_template.id,
        "sms_sender_id": sample_sms_sender.id,
    }

    v3_send_sms_notification_mock = mocker.patch("app.celery.v3.notification_tasks.v3_send_sms_notification.delay")
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_called_once_with(
        mocker.ANY,
        sample_sms_sender.sms_sender
    )
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
        "id": str(uuid4()),
        "notification_type": SMS_TYPE,
        "phone_number": "+18006982411",
        "template_id": sample_template.id,
    }

    v3_send_sms_notification_mock = mocker.patch(
        "app.celery.v3.notification_tasks.v3_send_sms_notification.delay"
    )

    get_default_sms_sender_id_mock = mocker.patch(
        "app.celery.v3.notification_tasks.get_default_sms_sender_id",
        return_value=(None, sample_sms_sender.id)
    )

    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)

    v3_send_sms_notification_mock.assert_called_once_with(
        mocker.ANY,
        sample_sms_sender.sms_sender
    )

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
        "id": str(uuid4()),
        "notification_type": SMS_TYPE,
        "phone_number": "+18006982411",
        "template_id": sample_template.id,
        "sms_sender_id": '111a1111-aaaa-1aa1-aa11-a1111aa1a1a1',
    }

    v3_send_sms_notification_mock = mocker.patch("app.celery.v3.notification_tasks.v3_send_sms_notification.delay")
    v3_process_notification(request_data, sample_service.id, None, KEY_TYPE_TEST)
    v3_send_sms_notification_mock.assert_not_called()


def test_v3_send_sms_notification(notify_db_session, mocker, sample_notification, sample_sms_sender):
    assert sample_notification.notification_type == SMS_TYPE

    client_mock = mocker.Mock()
    client_mock.send_sms = mocker.Mock(return_value="provider reference")
    client_mock.get_name = mocker.Mock(return_value="client name")
    mocker.patch("app.celery.v3.notification_tasks.clients.get_sms_client", return_value=client_mock)

    v3_send_sms_notification(sample_notification, sample_sms_sender.sms_sender)
    client_mock.send_sms.assert_called_once_with(
        sample_notification.to,
        sample_notification.content,
        sample_notification.client_reference,
        True,
        sample_sms_sender.sms_sender
    )

    query = select(Notification).where(Notification.id == sample_notification.id)
    notification = notify_db_session.session.execute(query).one().Notification
    assert notification.status == NOTIFICATION_SENT
    assert notification.reference == "provider reference"
    assert notification.sent_by == "client name"

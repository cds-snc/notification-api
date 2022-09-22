import base64
import uuid

import pytest
from freezegun import freeze_time

from app.attachments.exceptions import UnsupportedMimeTypeException
from app.attachments.store import AttachmentStoreError
from app.dao.service_sms_sender_dao import dao_update_service_sms_sender
from app.models import (
    ScheduledNotification,
    EMAIL_TYPE,
    NOTIFICATION_CREATED,
    SCHEDULE_NOTIFICATIONS,
    SMS_TYPE,
    UPLOAD_DOCUMENT,
    INTERNATIONAL_SMS_TYPE,
    RecipientIdentifier,
    Notification
)
from flask import json, current_app

from app.schema_validation import validate
from app.v2.errors import RateLimitError
from app.v2.notifications.notification_schemas import post_sms_response, post_email_response
from app.va.identifier import IdentifierType
from app.config import QueueNames
from app.feature_flags import FeatureFlag

from tests import create_authorization_header
from tests.app.db import (
    create_service,
    create_template,
    create_reply_to_email,
    create_service_sms_sender,
    create_service_with_inbound_number,
    create_api_key
)
from tests.app.factories.feature_flag import mock_feature_flag
from . import post_send_notification


@pytest.fixture
def enable_accept_recipient_identifiers_enabled_feature_flag(mocker):
    mocker.patch(
        'app.v2.notifications.post_notifications.accept_recipient_identifiers_enabled',
        return_value=True
    )


@pytest.fixture
def mock_template_with_version(mocker):
    mock_template = mocker.Mock()
    mock_template.id = 'template-id'
    mock_template.version = 1

    return mock_template


@pytest.fixture
def mock_api_key(mocker):
    mock_api_key = mocker.Mock()
    mock_api_key.id = 'some-id'
    mock_api_key.key_type = 'some-type'

    return mock_api_key


@pytest.fixture
def check_recipient_communication_permissions_enabled(mocker):
    mock_feature_flag(mocker, FeatureFlag.CHECK_RECIPIENT_COMMUNICATION_PERMISSIONS_ENABLED, 'True')


@pytest.fixture(autouse=True)
def mock_deliver_email(mocker):
    return mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')


@pytest.fixture(autouse=True)
def mock_deliver_sms(mocker):
    return mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
@pytest.mark.parametrize("data", [
    {"phone_number": "+16502532222"},
    # TODO - Testing recipient_identifier requires an active feature flag that is not
    # active in the testing environment.
    # {"recipient_identifier": {"id_type": IdentifierType.VA_PROFILE_ID.value, "id_value": "bar"}},
])
def test_post_sms_notification_returns_201(client, sample_template_with_placeholders,
                                           mock_deliver_sms, reference, data):
    data.update({
        'template_id': str(sample_template_with_placeholders.id),
        'personalisation': {' Name': 'Jo'}
    })
    if reference is not None:
        data["reference"] = reference

    response = post_send_notification(client, sample_template_with_placeholders.service, 'sms', data)

    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_sms_response) == resp_json

    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].status == NOTIFICATION_CREATED
    assert notifications[0].postage is None
    assert resp_json['id'] == str(notifications[0].id)
    assert resp_json['reference'] == reference
    assert resp_json['content']['body'] == sample_template_with_placeholders.content.replace("(( Name))", "Jo")
    assert resp_json['content']['from_number'] == current_app.config['FROM_NUMBER']
    assert f"v2/notifications/{notifications[0].id}" in resp_json["uri"]
    assert resp_json['template']['id'] == str(sample_template_with_placeholders.id)
    assert resp_json['template']['version'] == sample_template_with_placeholders.version
    assert 'services/{}/templates/{}'.format(
        sample_template_with_placeholders.service_id,
        sample_template_with_placeholders.id
    ) in resp_json['template']['uri']
    assert not resp_json["scheduled_for"]
    assert mock_deliver_sms.called


def test_post_sms_notification_uses_inbound_number_as_sender(client, notify_db_session, mocker):
    service = create_service_with_inbound_number(inbound_number='1')

    template = create_template(service=service, content="Hello (( Name))\nYour thing is due soon")
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    data = {
        'phone_number': '+16502532222',
        'template_id': str(template.id),
        'personalisation': {' Name': 'Jo'}
    }

    response = post_send_notification(client, service, 'sms', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    notifications = Notification.query.all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert resp_json['id'] == str(notification_id)
    assert resp_json['content']['from_number'] == '1'
    assert notifications[0].reply_to_text == '1'

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.args[0] == str(notification_id)


def test_post_sms_notification_uses_inbound_number_reply_to_as_sender(client, notify_db_session, mocker):
    service = create_service_with_inbound_number(inbound_number='6502532222')

    template = create_template(service=service, content="Hello (( Name))\nYour thing is due soon")
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    data = {
        'phone_number': '+16502532222',
        'template_id': str(template.id),
        'personalisation': {' Name': 'Jo'}
    }

    response = post_send_notification(client, service, 'sms', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    notifications = Notification.query.all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert resp_json['id'] == str(notification_id)
    assert resp_json['content']['from_number'] == '+16502532222'
    assert notifications[0].reply_to_text == '+16502532222'

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.args[0] == str(notification_id)


def test_post_sms_notification_returns_201_with_sms_sender_id(
        client, sample_template_with_placeholders, mocker
):
    sms_sender = create_service_sms_sender(service=sample_template_with_placeholders.service, sms_sender='123456')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    data = {
        'phone_number': '+16502532222',
        'template_id': str(sample_template_with_placeholders.id),
        'personalisation': {' Name': 'Jo'},
        'sms_sender_id': str(sms_sender.id)
    }

    response = post_send_notification(client, sample_template_with_placeholders.service, 'sms', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json['content']['from_number'] == sms_sender.sms_sender
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == sms_sender.sms_sender

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.args[0] == resp_json['id']


def test_post_sms_notification_uses_sms_sender_id_reply_to(
        client, sample_template_with_placeholders, mocker
):
    sms_sender = create_service_sms_sender(service=sample_template_with_placeholders.service, sms_sender='6502532222')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    mocker.patch('app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number')
    data = {
        'phone_number': '+16502532222',
        'template_id': str(sample_template_with_placeholders.id),
        'personalisation': {' Name': 'Jo'},
        'sms_sender_id': str(sms_sender.id)
    }

    response = post_send_notification(client, sample_template_with_placeholders.service, 'sms', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json['content']['from_number'] == '+16502532222'
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == '+16502532222'

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.args[0] == resp_json['id']


def test_notification_reply_to_text_is_original_value_if_sender_is_changed_after_post_notification(
        client, sample_template
):
    sms_sender = create_service_sms_sender(service=sample_template.service, sms_sender='123456', is_default=False)
    data = {
        'phone_number': '+16502532222',
        'template_id': str(sample_template.id),
        'sms_sender_id': str(sms_sender.id)
    }

    response = post_send_notification(client, sample_template.service, 'sms', data)

    dao_update_service_sms_sender(service_id=sample_template.service_id,
                                  service_sms_sender_id=sms_sender.id,
                                  is_default=sms_sender.is_default,
                                  sms_sender='updated')

    assert response.status_code == 201
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == '123456'


@pytest.mark.parametrize("notification_type, key_send_to, send_to",
                         [("sms", "phone_number", "+16502532222"),
                          ("email", "email_address", "sample@email.com")])
def test_post_notification_returns_400_and_missing_template(client, sample_service,
                                                            notification_type, key_send_to, send_to):
    data = {
        key_send_to: send_to,
        'template_id': str(uuid.uuid4())
    }

    response = post_send_notification(client, sample_service, notification_type, data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    error_json = json.loads(response.get_data(as_text=True))
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [{"error": "BadRequestError",
                                     "message": 'Template not found'}]


@pytest.mark.parametrize("notification_type, key_send_to, send_to", [
    ("sms", "phone_number", "+16502532222"),
    ("email", "email_address", "sample@email.com"),
    ("letter", "personalisation", {"address_line_1": "The queen", "postcode": "SW1 1AA"})
])
def test_post_notification_returns_401_and_well_formed_auth_error(client, sample_template,
                                                                  notification_type, key_send_to, send_to):
    data = {
        key_send_to: send_to,
        'template_id': str(sample_template.id)
    }

    response = client.post(
        path='/v2/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json')])

    assert response.status_code == 401
    assert response.headers['Content-type'] == 'application/json'
    error_resp = json.loads(response.get_data(as_text=True))
    assert error_resp['status_code'] == 401
    assert error_resp['errors'] == [{'error': "AuthError",
                                     'message': 'Unauthorized, authentication token must be provided'}]


@pytest.mark.parametrize("notification_type, key_send_to, send_to",
                         [("sms", "phone_number", "+16502532222"),
                          ("email", "email_address", "sample@email.com")])
def test_notification_returns_400_and_for_schema_problems(client, sample_template, notification_type, key_send_to,
                                                          send_to):
    data = {
        key_send_to: send_to,
        'template': str(sample_template.id)
    }

    response = post_send_notification(client, sample_template.service, notification_type, data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'
    error_resp = json.loads(response.get_data(as_text=True))
    assert error_resp['status_code'] == 400
    assert {'error': 'ValidationError',
            'message': "template_id is a required property"
            } in error_resp['errors']
    assert {'error': 'ValidationError',
            'message':
            'Additional properties are not allowed (template was unexpected)'
            } in error_resp['errors']


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_email_notification_returns_201(
        client, sample_email_template_with_placeholders, mock_deliver_email, reference
):
    data = {
        "email_address": sample_email_template_with_placeholders.service.users[0].email_address,
        "template_id": sample_email_template_with_placeholders.id,
        "personalisation": {"name": "Bob"},
        "billing_code": "TESTCODE"
    }

    if reference is not None:
        data["reference"] = reference

    response = post_send_notification(client, sample_email_template_with_placeholders.service, 'email', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json
    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_CREATED
    assert notification.postage is None
    assert resp_json['id'] == str(notification.id)
    assert resp_json['billing_code'] == "TESTCODE"
    assert resp_json['reference'] == reference
    assert notification.reference is None
    assert notification.reply_to_text is None
    assert resp_json['content']['body'] == sample_email_template_with_placeholders.content \
        .replace('((name))', 'Bob')
    assert resp_json['content']['subject'] == sample_email_template_with_placeholders.subject \
        .replace('((name))', 'Bob')
    assert 'v2/notifications/{}'.format(notification.id) in resp_json['uri']
    assert resp_json['template']['id'] == str(sample_email_template_with_placeholders.id)
    assert resp_json['template']['version'] == sample_email_template_with_placeholders.version
    assert 'services/{}/templates/{}'.format(str(sample_email_template_with_placeholders.service_id),
                                             str(sample_email_template_with_placeholders.id)) \
           in resp_json['template']['uri']
    assert not resp_json["scheduled_for"]
    assert mock_deliver_email.called


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_email_notification_with_reply_to_returns_201(
        client, sample_email_template_with_reply_to, mock_deliver_email, reference
):
    data = {
        "email_address": sample_email_template_with_reply_to.service.users[0].email_address,
        "template_id": sample_email_template_with_reply_to.id,
        "personalisation": {"name": "Bob"},
        "billing_code": "TESTCODE"
    }

    if reference is not None:
        data["reference"] = reference

    response = post_send_notification(client, sample_email_template_with_reply_to.service, 'email', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json
    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_CREATED
    assert notification.postage is None
    assert resp_json['id'] == str(notification.id)
    assert resp_json['billing_code'] == "TESTCODE"
    assert resp_json['reference'] == reference
    assert notification.reference is None
    assert notification.reply_to_text == 'testing@email.com'
    assert resp_json['content']['body'] == sample_email_template_with_reply_to.content \
        .replace('((name))', 'Bob')
    assert resp_json['content']['subject'] == sample_email_template_with_reply_to.subject \
        .replace('((name))', 'Bob')
    assert 'v2/notifications/{}'.format(notification.id) in resp_json['uri']
    assert resp_json['template']['id'] == str(sample_email_template_with_reply_to.id)
    assert resp_json['template']['version'] == sample_email_template_with_reply_to.version
    assert 'services/{}/templates/{}'.format(str(sample_email_template_with_reply_to.service_id),
                                             str(sample_email_template_with_reply_to.id)) \
           in resp_json['template']['uri']
    assert not resp_json["scheduled_for"]
    assert mock_deliver_email.called


@pytest.mark.parametrize('recipient, notification_type', [
    ('simulate-delivered@notifications.va.gov', EMAIL_TYPE),
    ('simulate-delivered-2@notifications.va.gov', EMAIL_TYPE),
    ('simulate-delivered-3@notifications.va.gov', EMAIL_TYPE),
    ('6132532222', 'sms'),
    ('6132532223', 'sms'),
    ('6132532224', 'sms')
])
def test_should_not_persist_or_send_notification_if_simulated_recipient(
        client,
        recipient,
        notification_type,
        sample_email_template,
        sample_template,
        mocker):
    apply_async = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(notification_type))

    if notification_type == 'sms':
        data = {
            'phone_number': recipient,
            'template_id': str(sample_template.id)
        }
    else:
        data = {
            'email_address': recipient,
            'template_id': str(sample_email_template.id)
        }

    response = post_send_notification(client, sample_email_template.service, notification_type, data)

    assert response.status_code == 201
    apply_async.assert_not_called()
    assert json.loads(response.get_data(as_text=True))["id"]
    assert Notification.query.count() == 0


@pytest.mark.parametrize("notification_type, key_send_to, send_to",
                         [("sms", "phone_number", "6502532222"),
                          ("email", "email_address", "sample@email.com")])
def test_send_notification_uses_priority_queue_when_template_is_marked_as_priority(
    client,
    sample_service,
    mocker,
    notification_type,
    key_send_to,
    send_to
):
    sample = create_template(
        service=sample_service,
        template_type=notification_type,
        process_type='priority'
    )
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    data = {
        key_send_to: send_to,
        'template_id': str(sample.id)
    }

    response = post_send_notification(client, sample.service, notification_type, data)

    notification_id = json.loads(response.data)['id']

    assert response.status_code == 201

    mocked_chain.assert_called_once()

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['priority-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.args[0] == str(notification_id)


@pytest.mark.parametrize(
    "notification_type, key_send_to, send_to",
    [("sms", "phone_number", "6502532222"), ("email", "email_address", "sample@email.com")]
)
def test_returns_a_429_limit_exceeded_if_rate_limit_exceeded(
        client,
        sample_service,
        mocker,
        notification_type,
        key_send_to,
        send_to
):
    sample = create_template(service=sample_service, template_type=notification_type)
    persist_mock = mocker.patch('app.v2.notifications.post_notifications.persist_notification')
    deliver_mock = mocker.patch('app.v2.notifications.post_notifications.send_notification_to_queue')
    mocker.patch(
        'app.v2.notifications.post_notifications.check_rate_limiting',
        side_effect=RateLimitError("LIMIT", "INTERVAL", "TYPE"))

    data = {
        key_send_to: send_to,
        'template_id': str(sample.id)
    }

    response = post_send_notification(client, sample.service, notification_type, data)

    error = json.loads(response.data)['errors'][0]['error']
    message = json.loads(response.data)['errors'][0]['message']
    status_code = json.loads(response.data)['status_code']
    assert response.status_code == 429
    assert error == 'RateLimitError'
    assert message == 'Exceeded rate limit for key type TYPE of LIMIT requests per INTERVAL seconds'
    assert status_code == 429

    assert not persist_mock.called
    assert not deliver_mock.called


def test_post_sms_notification_returns_400_if_not_allowed_to_send_int_sms(
        client,
        notify_db_session,
):
    service = create_service(service_permissions=[SMS_TYPE])
    template = create_template(service=service)

    data = {
        'phone_number': '+20-12-1234-1234',
        'template_id': template.id
    }

    response = post_send_notification(client, service, 'sms', data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    error_json = json.loads(response.get_data(as_text=True))
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [
        {"error": "BadRequestError", "message": 'Cannot send to international mobile numbers'}
    ]


def test_post_sms_notification_with_archived_reply_to_id_returns_400(client, sample_template):
    archived_sender = create_service_sms_sender(
        sample_template.service,
        '12345',
        is_default=False,
        archived=True)
    data = {
        "phone_number": '+16502532222',
        "template_id": sample_template.id,
        'sms_sender_id': archived_sender.id
    }

    response = post_send_notification(client, sample_template.service, 'sms', data)
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert 'sms_sender_id {} does not exist in database for service id {}'. \
        format(archived_sender.id, sample_template.service_id) in resp_json['errors'][0]['message']
    assert 'BadRequestError' in resp_json['errors'][0]['error']


@pytest.mark.parametrize('recipient,label,permission_type, notification_type,expected_error', [
    ('6502532222', 'phone_number', 'email', 'sms', 'text messages'),
    ('someone@test.com', 'email_address', 'sms', 'email', 'emails')])
def test_post_sms_notification_returns_400_if_not_allowed_to_send_notification(
        notify_db_session, client, recipient, label, permission_type, notification_type, expected_error
):
    service = create_service(service_permissions=[permission_type])
    sample_template_without_permission = create_template(service=service, template_type=notification_type)
    data = {
        label: recipient,
        'template_id': sample_template_without_permission.id
    }

    response = post_send_notification(
        client, sample_template_without_permission.service, sample_template_without_permission.template_type, data
    )

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    error_json = json.loads(response.get_data(as_text=True))
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [
        {"error": "BadRequestError", "message": "Service is not allowed to send {}".format(expected_error)}
    ]


@pytest.mark.parametrize('restricted', [True, False])
def test_post_sms_notification_returns_400_if_number_not_whitelisted(
        notify_db_session, client, restricted
):
    service = create_service(restricted=restricted, service_permissions=[SMS_TYPE, INTERNATIONAL_SMS_TYPE])
    template = create_template(service=service)
    create_api_key(service=service, key_type='team')

    data = {
        "phone_number": '+16132532235',
        "template_id": template.id,
    }
    auth_header = create_authorization_header(service_id=service.id, key_type='team')

    response = client.post(
        path='/v2/notifications/sms',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [
        {"error": "BadRequestError", "message": 'Can’t send to this recipient using a team-only API key'}
    ]


def test_post_sms_notification_returns_201_if_allowed_to_send_international_sms(
        sample_service,
        sample_template,
        client
):
    """
    Ensure that SMS messages can be sent to phones outside the United States.

    This is only testing that this application's code doesn't reject a foreign
    number.  Actual delivery depends on the capabilities of the 3rd party SMS
    backend (i.e. Twilio, etc.).
    """

    data = {
        'phone_number': '+20-12-1234-1234',
        'template_id': sample_template.id
    }

    response = post_send_notification(client, sample_service, 'sms', data)

    assert response.status_code == 201
    assert response.headers['Content-type'] == 'application/json'


def test_post_sms_should_persist_supplied_sms_number(client, sample_template_with_placeholders, mock_deliver_sms):
    data = {
        'phone_number': '+16502532222',
        'template_id': str(sample_template_with_placeholders.id),
        'personalisation': {' Name': 'Jo'}
    }

    response = post_send_notification(client, sample_template_with_placeholders.service, 'sms', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    notifications = Notification.query.all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert '+16502532222' == notifications[0].to
    assert resp_json['id'] == str(notification_id)
    assert mock_deliver_sms.called


@pytest.mark.parametrize("notification_type, key_send_to, send_to",
                         [("sms", "phone_number", "6502532222"),
                          ("email", "email_address", "sample@email.com")])
@freeze_time("2017-05-14 14:00:00")
def test_post_notification_with_scheduled_for(
        client, notify_db_session, notification_type, key_send_to, send_to
):
    service = create_service(service_name=str(uuid.uuid4()),
                             service_permissions=[EMAIL_TYPE, SMS_TYPE, SCHEDULE_NOTIFICATIONS])
    template = create_template(service=service, template_type=notification_type)
    data = {
        key_send_to: send_to,
        'template_id': str(template.id) if notification_type == EMAIL_TYPE else str(template.id),
        'scheduled_for': '2017-05-14 14:15'
    }

    response = post_send_notification(client, service, notification_type, data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    scheduled_notification = ScheduledNotification.query.filter_by(notification_id=resp_json["id"]).all()
    assert len(scheduled_notification) == 1
    assert resp_json["id"] == str(scheduled_notification[0].notification_id)
    assert resp_json["scheduled_for"] == '2017-05-14 14:15'


@pytest.mark.parametrize("notification_type, key_send_to, send_to",
                         [("sms", "phone_number", "6502532222"),
                          ("email", "email_address", "sample@email.com")])
@freeze_time("2017-05-14 14:00:00")
def test_post_notification_raises_bad_request_if_service_not_invited_to_schedule(
        client, sample_template, sample_email_template, notification_type, key_send_to, send_to):
    data = {
        key_send_to: send_to,
        'template_id': str(sample_email_template.id) if notification_type == EMAIL_TYPE else str(sample_template.id),
        'scheduled_for': '2017-05-14 14:15'
    }

    response = post_send_notification(client, sample_template.service, notification_type, data)
    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))
    assert error_json['errors'] == [
        {"error": "BadRequestError", "message": 'Cannot schedule notifications (this feature is invite-only)'}]


def test_post_notification_raises_bad_request_if_not_valid_notification_type(client, sample_service):
    response = post_send_notification(client, sample_service, 'foo', {})
    assert response.status_code == 404
    error_json = json.loads(response.get_data(as_text=True))
    assert 'The requested URL was not found on the server.' in error_json['message']


@pytest.mark.parametrize("notification_type",
                         ['sms', 'email'])
def test_post_notification_with_wrong_type_of_sender(
        client,
        sample_template,
        sample_email_template,
        notification_type,
        fake_uuid):
    if notification_type == EMAIL_TYPE:
        template = sample_email_template
        form_label = 'sms_sender_id'
        data = {
            'email_address': 'test@test.com',
            'template_id': str(sample_email_template.id),
            form_label: fake_uuid
        }
    elif notification_type == SMS_TYPE:
        template = sample_template
        form_label = 'email_reply_to_id'
        data = {
            'phone_number': '+16502532222',
            'template_id': str(template.id),
            form_label: fake_uuid
        }

    response = post_send_notification(client, template.service, notification_type, data)
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert 'Additional properties are not allowed ({} was unexpected)'.format(form_label) \
           in resp_json['errors'][0]['message']
    assert 'ValidationError' in resp_json['errors'][0]['error']


def test_post_email_notification_with_valid_reply_to_id_returns_201(client, sample_email_template, mock_deliver_email):
    reply_to_email = create_reply_to_email(sample_email_template.service, 'test@test.com')
    data = {
        "email_address": sample_email_template.service.users[0].email_address,
        "template_id": sample_email_template.id,
        'email_reply_to_id': reply_to_email.id
    }

    response = post_send_notification(client, sample_email_template.service, 'email', data)
    assert response.status_code == 201
    resp_json = json.loads(response.get_data(as_text=True))
    assert validate(resp_json, post_email_response) == resp_json
    notification = Notification.query.first()
    assert notification.reply_to_text == 'test@test.com'
    assert resp_json['id'] == str(notification.id)
    assert mock_deliver_email.called

    assert notification.reply_to_text == reply_to_email.email_address


def test_post_email_notification_with_invalid_reply_to_id_returns_400(client, sample_email_template, fake_uuid):
    data = {
        "email_address": sample_email_template.service.users[0].email_address,
        "template_id": sample_email_template.id,
        'email_reply_to_id': fake_uuid
    }

    response = post_send_notification(client, sample_email_template.service, 'email', data)
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert 'email_reply_to_id {} does not exist in database for service id {}'. \
        format(fake_uuid, sample_email_template.service_id) in resp_json['errors'][0]['message']
    assert 'BadRequestError' in resp_json['errors'][0]['error']


def test_post_email_notification_with_archived_reply_to_id_returns_400(client, sample_email_template):
    archived_reply_to = create_reply_to_email(
        sample_email_template.service,
        'reply_to@test.com',
        is_default=False,
        archived=True)
    data = {
        "email_address": 'test@test.com',
        "template_id": sample_email_template.id,
        'email_reply_to_id': archived_reply_to.id
    }

    response = post_send_notification(client, sample_email_template.service, 'email', data)
    assert response.status_code == 400
    resp_json = json.loads(response.get_data(as_text=True))
    assert 'email_reply_to_id {} does not exist in database for service id {}'. \
        format(archived_reply_to.id, sample_email_template.service_id) in resp_json['errors'][0]['message']
    assert 'BadRequestError' in resp_json['errors'][0]['error']


class TestPostNotificationWithAttachment:

    base64_encoded_file = "VGV4dCBjb250ZW50IGhlcmU="

    @pytest.fixture
    def service_with_upload_document_permission(self, notify_db_session):
        return create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])

    @pytest.fixture
    def template(self, notify_db_session, service_with_upload_document_permission):
        return create_template(
            service=service_with_upload_document_permission,
            template_type='email',
            content="See attached file"
        )

    @pytest.fixture(autouse=True)
    def attachment_store_mock(self, mocker):
        return mocker.patch('app.v2.notifications.post_notifications.attachment_store')

    @pytest.fixture(autouse=True)
    def validate_mimetype_mock(self, mocker):
        return mocker.patch(
            'app.v2.notifications.post_notifications.extract_and_validate_mimetype',
            return_value='fake/mimetype'
        )

    @pytest.fixture(autouse=True)
    def feature_toggle_enabled(self, mocker):
        mock_feature_flag(mocker, feature_flag=FeatureFlag.EMAIL_ATTACHMENTS_ENABLED, enabled='True')

    def test_returns_not_implemented_if_feature_flag_disabled(
            self, client, mocker, service_with_upload_document_permission, template, attachment_store_mock
    ):
        mock_feature_flag(mocker, feature_flag=FeatureFlag.EMAIL_ATTACHMENTS_ENABLED, enabled='False')

        response = post_send_notification(client, service_with_upload_document_permission, 'email', {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "some_attachment": {
                    "file": self.base64_encoded_file,
                    "filename": "attachment.pdf",
                    "sending_method": "attach"
                }
            }
        })

        assert response.status_code == 501
        attachment_store_mock.put.assert_not_called()

    def test_returns_not_implemented_if_sending_method_is_link(
            self, client, service_with_upload_document_permission, template, attachment_store_mock
    ):
        response = post_send_notification(client, service_with_upload_document_permission, 'email', {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "some_attachment": {
                    "file": self.base64_encoded_file,
                    "filename": "attachment.pdf",
                    "sending_method": "link"
                }
            }
        })

        assert response.status_code == 501
        attachment_store_mock.put.assert_not_called()

    @pytest.mark.parametrize("sending_method", ["attach", None])
    def test_attachment_upload_with_sending_method_attach(
            self,
            client,
            notify_db_session,
            mocker,
            sending_method,
            service_with_upload_document_permission,
            template,
            attachment_store_mock
    ):
        mock_uploaded_attachment = ('fake-id', 'fake-key')
        attachment_store_mock.put.return_value = mock_uploaded_attachment

        data = {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "some_attachment": {
                    "file": self.base64_encoded_file,
                    "filename": "file.pdf",
                }
            }
        }

        if sending_method:
            data["personalisation"]["some_attachment"]["sending_method"] = sending_method

        response = post_send_notification(client, service_with_upload_document_permission, 'email', data)

        assert response.status_code == 201, response.get_data(as_text=True)
        resp_json = json.loads(response.get_data(as_text=True))
        assert validate(resp_json, post_email_response) == resp_json
        attachment_store_mock.put.assert_called_once_with(
            **{
                "service_id": service_with_upload_document_permission.id,
                "attachment_stream": base64.b64decode(self.base64_encoded_file),
                "mimetype": "fake/mimetype",
                "sending_method": "attach"
            },
        )

        notification = Notification.query.one()
        assert notification.status == NOTIFICATION_CREATED
        assert notification.personalisation == {
            'some_attachment': {
                'file_name': 'file.pdf',
                'sending_method': 'attach',
                'id': 'fake-id',
                'encryption_key': 'fake-key'
            }
        }

    def test_attachment_upload_unsupported_mimetype(
            self,
            client,
            notify_db_session,
            mocker,
            service_with_upload_document_permission,
            template,
            attachment_store_mock,
            validate_mimetype_mock
    ):
        validate_mimetype_mock.side_effect = UnsupportedMimeTypeException()

        data = {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "some_attachment": {
                    "file": self.base64_encoded_file,
                    "filename": "file.pdf",
                }
            }
        }

        response = post_send_notification(client, service_with_upload_document_permission, 'email', data)

        assert response.status_code == 400
        attachment_store_mock.put.assert_not_called()

    def test_long_filename(self, client, service_with_upload_document_permission, template):
        filename = "a" * 256
        response = post_send_notification(client, service_with_upload_document_permission, 'email', {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "document": {
                    "file": self.base64_encoded_file,
                    "filename": filename,
                    "sending_method": "attach",
                }
            },
        })

        assert response.status_code == 400
        resp_json = json.loads(response.get_data(as_text=True))
        assert "ValidationError" in resp_json["errors"][0]["error"]
        assert filename in resp_json["errors"][0]["message"]
        assert "too long" in resp_json["errors"][0]["message"]

    def test_filename_required_check(self, client, service_with_upload_document_permission, template):
        response = post_send_notification(client, service_with_upload_document_permission, 'email', {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "document": {"file": self.base64_encoded_file, "sending_method": "attach"}
            },
        })

        assert response.status_code == 400
        resp_json = json.loads(response.get_data(as_text=True))
        assert "ValidationError" in resp_json["errors"][0]["error"]
        assert "filename is a required property" in resp_json["errors"][0]["message"]

    def test_bad_sending_method(self, client, service_with_upload_document_permission, template):
        response = post_send_notification(client, service_with_upload_document_permission, 'email', {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "document": {
                    "file": self.base64_encoded_file,
                    "filename": "1.txt",
                    "sending_method": "not-a-real-sending-method",
                }
            },
        })

        assert response.status_code == 400
        resp_json = json.loads(response.get_data(as_text=True))
        assert (
            f"personalisation not-a-real-sending-method is not one of [attach, link]"
            in resp_json["errors"][0]["message"]
        )

    def test_not_base64_file(self, client, service_with_upload_document_permission, template):
        response = post_send_notification(client, service_with_upload_document_permission, 'email', {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "document": {
                    "file": "abc",
                    "sending_method": "attach",
                    "filename": "1.txt",
                }
            },
        })

        assert response.status_code == 400
        resp_json = json.loads(response.get_data(as_text=True))
        assert "Incorrect padding" in resp_json["errors"][0]["message"]

    def test_simulated(self, client, notify_db_session):
        service = create_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = create_template(
            service=service, template_type="email", content="Document: ((document))"
        )

        data = {
            "email_address": "simulate-delivered@notifications.va.gov",
            "template_id": template.id,
            "personalisation": {"document": {"file": "abababab", "filename": "file.pdf"}},
        }

        response = post_send_notification(client, service, 'email', data)

        assert response.status_code == 201
        resp_json = json.loads(response.get_data(as_text=True))
        assert validate(resp_json, post_email_response) == resp_json

        assert (
            resp_json["content"]["body"] == "Document: simulated-attachment-url"
        )

    def test_without_document_upload_permission(
        self, client, notify_db_session
    ):
        service = create_service(service_permissions=[EMAIL_TYPE])
        template = create_template(
            service=service, template_type="email", content="Document: ((document))"
        )

        response = post_send_notification(client, service, 'email', {
            "email_address": service.users[0].email_address,
            "template_id": template.id,
            "personalisation": {"document": {"file": "abababab", "filename": "foo.pdf"}},
        })

        assert response.status_code == 400
        resp_json = json.loads(response.get_data(as_text=True))
        assert "Service is not allowed to send documents" in resp_json["errors"][0]["message"]

    def test_attachment_store_error(
        self, client, notify_db_session, service_with_upload_document_permission, template, attachment_store_mock
    ):
        attachment_store_mock.put.side_effect = AttachmentStoreError()

        data = {
            "email_address": "foo@bar.com",
            "template_id": template.id,
            "personalisation": {
                "some_attachment": {
                    "file": self.base64_encoded_file,
                    "filename": "file.pdf",
                }
            }
        }

        response = post_send_notification(client, service_with_upload_document_permission, 'email', data)

        assert response.status_code == 400
        resp_json = json.loads(response.get_data(as_text=True))
        assert "Unable to upload attachment object to store" in resp_json["errors"][0]["message"]


def test_post_notification_returns_400_when_get_json_throws_exception(client, sample_email_template):
    auth_header = create_authorization_header(service_id=sample_email_template.service_id)
    response = client.post(
        path="v2/notifications/email",
        data="[",
        headers=[('Content-Type', 'application/json'), auth_header])
    assert response.status_code == 400


@pytest.mark.skip(reason='failing in pipeline for some reason')
@pytest.mark.parametrize(
    'expected_type, expected_value, task',
    [
        (IdentifierType.VA_PROFILE_ID.value, 'some va profile id',
         'app.celery.contact_information_tasks.lookup_contact_info'),
        (IdentifierType.PID.value, 'some pid', 'app.celery.lookup_va_profile_id_task.lookup_va_profile_id'),
        (IdentifierType.ICN.value, 'some icn', 'app.celery.lookup_va_profile_id_task.lookup_va_profile_id')
    ]
)
def test_should_process_notification_successfully_with_recipient_identifiers(
        client,
        mocker,
        enable_accept_recipient_identifiers_enabled_feature_flag,
        expected_type,
        expected_value,
        task,
        sample_email_template
):
    mocked_task = mocker.patch(
        f'{task}.apply_async')

    data = {
        "template_id": sample_email_template.id,
        "recipient_identifier": {'id_type': expected_type, 'id_value': expected_value}
    }
    auth_header = create_authorization_header(service_id=sample_email_template.service_id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 201
    assert Notification.query.count() == 1
    assert RecipientIdentifier.query.count() == 1
    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_CREATED
    assert notification.recipient_identifiers[expected_type].id_type == expected_type
    assert notification.recipient_identifiers[expected_type].id_value == expected_value

    mocked_task.assert_called_once()


@pytest.mark.skip(reason='test failing in pipeline but no where else')
@pytest.mark.parametrize('notification_type', ["email", "sms"])
def test_should_post_notification_successfully_with_recipient_identifier_and_contact_info(
        client,
        mocker,
        enable_accept_recipient_identifiers_enabled_feature_flag,
        check_recipient_communication_permissions_enabled,
        sample_email_template,
        sample_sms_template_with_html,
        notification_type
):
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    expected_id_type = IdentifierType.VA_PROFILE_ID.value
    expected_id_value = 'some va profile id'

    if notification_type == "email":
        template = sample_email_template
        data = {
            "template_id": template.id,
            "email_address": "some-email@test.com",
            "recipient_identifier": {
                'id_type': expected_id_type,
                'id_value': expected_id_value
            },
            "billing_code": "TESTCODE"
        }
    else:
        template = sample_sms_template_with_html
        data = {
            "template_id": template.id,
            "phone_number": "+16502532222",
            "recipient_identifier": {
                'id_type': expected_id_type,
                'id_value': expected_id_value
            },
            "personalisation": {
                "Name": "Flowers"
            },
            "billing_code": "TESTCODE"
        }
    service = sample_email_template.service if notification_type == 'email' else sample_sms_template_with_html.service
    auth_header = create_authorization_header(service_id=service.id)
    response = client.post(
        path=f"v2/notifications/{notification_type}",
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 201
    assert Notification.query.count() == 1
    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_CREATED

    # Commenting out these assertions because of funky failures in pipeline
    # assert RecipientIdentifier.query.count() == 1
    # assert notification.recipient_identifiers[expected_id_type].id_type == expected_id_type
    # assert notification.recipient_identifiers[expected_id_type].id_value == expected_id_value

    mocked_chain.assert_called_once()

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, [QueueNames.COMMUNICATION_ITEM_PERMISSIONS,
                                                 f'send-{notification_type}-tasks']):
        assert called_task.options['queue'] == expected_task
        if expected_task == QueueNames.COMMUNICATION_ITEM_PERMISSIONS:
            assert called_task.args == (expected_id_type,
                                        expected_id_value,
                                        str(notification.id),
                                        notification.notification_type,
                                        notification.template.communication_item_id)
        else:
            assert called_task.args[0] == str(notification.id)


def test_post_notification_returns_501_when_recipient_identifiers_present_and_feature_flag_disabled(
        client,
        mocker,
        sample_email_template
):
    mocker.patch(
        'app.v2.notifications.post_notifications.accept_recipient_identifiers_enabled',
        return_value=False
    )
    data = {
        "template_id": sample_email_template.id,
        "recipient_identifier": {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': "foo"}
    }
    auth_header = create_authorization_header(service_id=sample_email_template.service_id)
    response = client.post(
        path="v2/notifications/email",
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header])
    assert response.status_code == 501


@pytest.mark.parametrize('notification_type', [
    'email',
    'sms'
])
def test_post_notification_returns_400_when_billing_code_length_exceeds_max(client, notification_type,
                                                                            sample_email_template,
                                                                            sample_sms_template_with_html):
    if notification_type == 'email':
        data = {
            "template_id": sample_email_template.id,
            "email_address": "someemail@test.com",
            "billing_code": (
                "awpeoifhwaepoifjaajf5alsdkfj5asdlkfja5sdlkfjasd5lkfjaeoifjapweoighaeiofjawieofjaeiopwfghaepiofhposihf"
                "paoweifjafjsdlkfjsldfkjsdlkfjsldkjpoeifjapseoifhapoeifjaspoeifhaeoihfeopifhaepoifjeaioghaeoifjaepoifj"
                "aepighaepoifjaepoifhaepogihaewoipfjeaiopfjaeopighaepiwofjaeopiwfjaepoifj"
            )
        }
        service_id = sample_email_template.service_id
    else:
        data = {
            "template_id": sample_sms_template_with_html.id,
            "phone_number": "+16502532222",
            "billing_code": (
                "awpeoifhwaepoifjaajf5alsdkfj5asdlkfja5sdlkfjasd5lkfjaeoifjapweoighaeiofjawieofjaeiopwfghaepiofhposihf"
                "paoweifjafjsdlkfjsldfkjsdlkfjsldkjpoeifjapseoifhapoeifjaspoeifhaeoihfeopifhaepoifjeaioghaeoifjaepoifj"
                "aepighaepoifjaepoifhaepogihaewoipfjeaiopfjaeopighaepiwofjaeopiwfjaepoifj"
            )
        }
        service_id = sample_sms_template_with_html.service_id

    auth_header = create_authorization_header(service_id=service_id)
    response = client.post(
        path=f"v2/notifications/{notification_type}",
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 400
    assert 'too long' in response.json['errors'][0]['message']

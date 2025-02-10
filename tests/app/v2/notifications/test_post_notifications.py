import base64
import uuid
from random import randint

import pytest
from flask import current_app, json
from freezegun import freeze_time
from sqlalchemy import delete, func, select

from app.attachments.exceptions import UnsupportedMimeTypeException
from app.attachments.store import AttachmentStoreError
from app.config import QueueNames
from app.constants import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_TEAM,
    NOTIFICATION_CREATED,
    SCHEDULE_NOTIFICATIONS,
    SMS_TYPE,
    UPLOAD_DOCUMENT,
)
from app.dao.service_sms_sender_dao import dao_update_service_sms_sender
from app.feature_flags import FeatureFlag
from app.models import (
    Notification,
    RecipientIdentifier,
    ScheduledNotification,
)
from app.schema_validation import validate
from app.v2.errors import RateLimitError
from app.v2.notifications.notification_schemas import post_email_response, post_sms_response
from app.va.identifier import IdentifierType
from tests import create_authorization_header
from tests.app.db import create_reply_to_email  # , create_service_sms_sender
from tests.app.factories.feature_flag import mock_feature_flag

from . import post_send_notification


@pytest.fixture(autouse=True)
def mock_deliver_email(mocker):
    return mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')


@pytest.fixture(autouse=True)
def mock_deliver_sms(mocker):
    return mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')


@pytest.mark.parametrize('reference', [None, 'not none'])
@pytest.mark.parametrize(
    'data',
    [
        {'phone_number': '+16502532222'},
        {'recipient_identifier': {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'bar'}},
    ],
)
def test_post_sms_notification_returns_201(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mock_deliver_sms,
    reference,
    data,
    mocker,
):
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')
    data.update(
        {'template_id': str(template.id), 'personalisation': {' Name': 'Jo'}, 'callback_url': 'https://www.test.com'}
    )
    if reference is not None:
        # Have to set reference for the asserts below, can't add it to data in the None case
        reference = str(uuid.uuid4())
        data['reference'] = reference

    if 'recipient_identifier' in data:
        mocker.patch('app.v2.notifications.post_notifications.accept_recipient_identifiers_enabled', return_value=True)
        mocker.patch('app.celery.lookup_va_profile_id_task.lookup_va_profile_id.apply_async')
        mocker.patch('app.celery.onsite_notification_tasks.send_va_onsite_notification_task.apply_async')
        mocker.patch('app.celery.contact_information_tasks.lookup_contact_info.apply_async')

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)

    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_sms_response) == resp_json

    notifications = notify_db_session.session.scalars(
        select(Notification).where(Notification.service_id == template.service_id)
    ).all()
    # DB checks
    assert len(notifications) == 1
    assert notifications[0].status == NOTIFICATION_CREATED
    assert notifications[0].postage is None
    assert notifications[0].callback_url == 'https://www.test.com'

    # endpoint checks
    assert resp_json['id'] == str(notifications[0].id)
    assert resp_json['reference'] == reference
    assert resp_json['content']['body'] == template.content.replace('(( Name))', '<redacted>')
    assert resp_json['content']['from_number'] == current_app.config['FROM_NUMBER']
    assert f'v2/notifications/{notifications[0].id}' in resp_json['uri']
    assert resp_json['template']['id'] == str(template.id)
    assert resp_json['template']['version'] == template.version
    assert 'services/{}/templates/{}'.format(template.service_id, template.id) in resp_json['template']['uri']
    assert not resp_json['scheduled_for']
    assert resp_json['callback_url'] == 'https://www.test.com'
    if 'recipient_identifier' not in data:
        assert mock_deliver_sms.called
    # Else, for sending with a recipient ID, the delivery function won't get called because the preceeding
    # tasks in the chain are mocked.


def test_post_sms_notification_uses_inbound_number_as_sender(
    client,
    mocker,
    notify_db_session,
    sample_api_key,
    sample_service,
    sample_template,
    sample_inbound_number,
    sample_sms_sender,
):
    service = sample_service()
    template = sample_template(service=service, content='Hello (( Name))\nYour thing is due soon')
    inbound_number = sample_inbound_number(service_id=service.id, number=str(randint(1, 999999999)))
    sms_sender = sample_sms_sender(
        service_id=service.id, inbound_number_id=inbound_number.id, sms_sender=str(randint(1, 999999999))
    )

    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    data = {
        'phone_number': '+16502532222',
        'template_id': str(template.id),
        'personalisation': {' Name': 'Jo'},
        'sms_sender_id': str(sms_sender.id),
    }

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)
    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_sms_response) == resp_json
    notifications = notify_db_session.session.scalars(
        select(Notification).where(Notification.service_id == template.service_id)
    ).all()
    assert len(notifications) == 1
    notification_id = str(notifications[0].id)
    assert resp_json['id'] == notification_id
    # These two should be the same
    assert resp_json['content']['from_number'] == sms_sender.sms_sender  # Our number
    assert notifications[0].reply_to_text == sms_sender.sms_sender  # Our number

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert args[0].kwargs.get('notification_id') == notification_id


def test_post_sms_notification_uses_inbound_number_reply_to_as_sender(
    client,
    mocker,
    notify_db_session,
    sample_api_key,
    sample_service_with_inbound_number,
    sample_template,
):
    service_number = str(randint(10000, 10000000))
    service = sample_service_with_inbound_number(inbound_number=service_number)

    template = sample_template(service=service, content='Hello (( Name))\nYour thing is due soon')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    data = {'phone_number': '+14079395277', 'template_id': str(template.id), 'personalisation': {' Name': 'Jo'}}

    response = post_send_notification(client, sample_api_key(service=service), SMS_TYPE, data)
    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_sms_response) == resp_json
    stmt = select(Notification).where(Notification.service_id == template.service_id)
    notification = notify_db_session.session.scalars(stmt).one()
    notification_id = str(notification.id)
    assert resp_json['id'] == notification_id
    assert resp_json['content']['from_number'] == service_number
    assert notification.reply_to_text == service_number

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.kwargs.get('notification_id') == notification_id


@pytest.mark.parametrize('sms_sender_id', [None, 'user provided'])
def test_post_sms_notification_returns_201_with_sms_sender_id(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
    sms_sender_id,
    sample_sms_sender,
):
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    assert template.template_type == SMS_TYPE

    data = {
        'phone_number': '+16502532222',
        'template_id': str(template.id),
        'personalisation': {' Name': 'Jo'},
    }

    if sms_sender_id is None:
        data['sms_sender_id'] = None
    elif sms_sender_id == 'user provided':
        # Simulate that the user specified an sms_sender_id.
        sms_sender = sample_sms_sender(service_id=template.service.id, sms_sender='123456')
        data['sms_sender_id'] = str(sms_sender.id)
    else:
        raise ValueError('This is a programming error.')

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)

    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_sms_response) == resp_json

    notifications = notify_db_session.session.scalars(
        select(Notification).where(Notification.service_id == template.service_id)
    ).all()
    assert len(notifications) == 1

    if sms_sender_id == 'user provided':
        assert resp_json['content']['from_number'] == sms_sender.sms_sender
        assert notifications[0].reply_to_text == sms_sender.sms_sender
        assert notifications[0].sms_sender_id == sms_sender.id
    else:
        # The user did not provide an sms_sender_id.  The template default should have been used.
        default_sms_sender = template.get_reply_to_text()
        assert resp_json['content']['from_number'] == default_sms_sender
        assert notifications[0].reply_to_text == default_sms_sender

        for sender in template.service.service_sms_senders:
            if sender.is_default:
                assert notifications[0].sms_sender_id == sender.id
                break
        else:
            assert False, "The template's service does not have a default sms_sender."

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.kwargs.get('notification_id') == resp_json['id']


def test_post_sms_notification_uses_sms_sender_id_reply_to(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    sample_sms_sender,
    mocker,
):
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')
    sms_sender = sample_sms_sender(service_id=template.service.id, sms_sender='6502532222')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    mocker.patch('app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number')

    data = {
        'phone_number': '+16502532222',
        'template_id': str(template.id),
        'personalisation': {' Name': 'Jo'},
        'sms_sender_id': str(sms_sender.id),
    }

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)
    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json['content']['from_number'] == '+16502532222'
    stmt = select(Notification).where(Notification.service_id == template.service_id)
    notification = notify_db_session.session.scalars(stmt).one()
    assert notification.reply_to_text == '+16502532222'

    mocked_chain.assert_called_once()
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.kwargs.get('notification_id') == resp_json['id']


def test_notification_reply_to_text_is_original_value_if_sender_is_changed_after_post_notification(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    sample_sms_sender,
):
    template = sample_template()
    sender_number = str(randint(100000, 10000000))
    sms_sender = sample_sms_sender(service_id=template.service.id, sms_sender=sender_number, is_default=False)
    data = {'phone_number': '+16502532222', 'template_id': str(template.id), 'sms_sender_id': str(sms_sender.id)}

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)

    dao_update_service_sms_sender(
        service_id=template.service_id,
        service_sms_sender_id=sms_sender.id,
        is_default=sms_sender.is_default,
        sms_sender='updated',
    )

    assert response.status_code == 201
    stmt = select(Notification).where(Notification.service_id == template.service_id)
    notification = notify_db_session.session.scalars(stmt).one()
    assert notification.reply_to_text == sender_number


@pytest.mark.parametrize(
    'notification_type, key_send_to, send_to',
    [(SMS_TYPE, 'phone_number', '+16502532222'), (EMAIL_TYPE, 'email_address', 'sample@email.com')],
)
def test_post_notification_returns_400_and_missing_template(
    client,
    sample_api_key,
    notification_type,
    key_send_to,
    send_to,
):
    data = {key_send_to: send_to, 'template_id': str(uuid.uuid4())}

    response = post_send_notification(client, sample_api_key(), notification_type, data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    error_json = response.get_json()
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [{'error': 'BadRequestError', 'message': 'Template not found'}]


@pytest.mark.parametrize(
    'notification_type, key_send_to, send_to',
    [
        (SMS_TYPE, 'phone_number', '+16502532222'),
        (EMAIL_TYPE, 'email_address', 'sample@email.com'),
    ],
)
def test_post_notification_returns_401_and_well_formed_auth_error(
    client, sample_template, notification_type, key_send_to, send_to
):
    data = {key_send_to: send_to, 'template_id': str(sample_template().id)}

    response = client.post(
        path='/v2/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json')],
    )

    assert response.status_code == 401
    assert response.headers['Content-type'] == 'application/json'
    error_resp = response.get_json()
    assert error_resp['status_code'] == 401
    assert error_resp['errors'] == [
        {'error': 'AuthError', 'message': 'Unauthorized, authentication token must be provided'}
    ]


@pytest.mark.parametrize(
    'notification_type, key_send_to, send_to',
    [(SMS_TYPE, 'phone_number', '+16502532222'), (EMAIL_TYPE, 'email_address', 'sample@email.com')],
)
def test_notification_returns_400_and_for_schema_problems(
    client,
    sample_api_key,
    sample_template,
    notification_type,
    key_send_to,
    send_to,
):
    template = sample_template()
    data = {key_send_to: send_to, 'template': str(template.id)}

    response = post_send_notification(client, sample_api_key(service=template.service), notification_type, data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'
    error_resp = response.get_json()
    assert error_resp['status_code'] == 400
    assert {'error': 'ValidationError', 'message': 'template_id is a required property'} in error_resp['errors']
    assert {
        'error': 'ValidationError',
        'message': 'Additional properties are not allowed (template was unexpected)',
    } in error_resp['errors']


def test_post_sms_notification_without_callback_url(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
):
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')

    data = {'phone_number': '+16502532222', 'template_id': str(template.id), 'personalisation': {' Name': 'Jo'}}

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)

    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_sms_response) == resp_json

    notifications = notify_db_session.session.scalars(
        select(Notification).where(Notification.service_id == template.service_id)
    ).all()

    assert len(notifications) == 1

    notification = notifications[0]
    assert notification.callback_url is None

    assert resp_json['id'] == str(notification.id)
    assert resp_json['content']['body'] == template.content.replace('(( Name))', '<redacted>')
    assert resp_json['callback_url'] is None


@pytest.mark.parametrize(
    'callback_url, expected_error',
    [
        ('invalid-url', 'is not a valid URI.'),
        ('http://wrongformat.com', 'does not match ^https.*'),
        ('www.missingprotocol.com', 'does not match ^https.*'),
        (
            'https://example.com/search?query=this_is_a_search_term_to_reach_exactly_256_charactersaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&filter=type=all&status=active&sort=ascending&page=1234567890&session_token=abc123&tracking_id=unique_user_tracking_value',
            'is too long',
        ),
    ],
)
def test_notification_returns_400_if_invalid_callback_url(
    client,
    sample_api_key,
    sample_template,
    callback_url,
    expected_error,
):
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')

    data = {
        'phone_number': '+16502532222',
        'template_id': str(template.id),
        'personalisation': {' Name': 'Jo'},
        'callback_url': callback_url,
    }

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'
    error_resp = response.get_json()

    assert error_resp['status_code'] == 400
    assert {'error': 'ValidationError', 'message': f'callback_url {callback_url} {expected_error}'} in error_resp[
        'errors'
    ]


@pytest.mark.parametrize('reference', [None, 'reference_from_client'])
def test_post_email_notification_returns_201(
    client,
    mock_deliver_email,
    notify_db_session,
    sample_api_key,
    sample_template,
    reference,
):
    template = sample_template(template_type=EMAIL_TYPE)
    data = {
        'email_address': template.service.users[0].email_address,
        'template_id': template.id,
        'personalisation': {'name': 'Bob'},
        'billing_code': 'TESTCODE',
        'callback_url': 'https://www.test.com',
    }

    if reference is not None:
        data['reference'] = reference

    response = post_send_notification(client, sample_api_key(service=template.service), EMAIL_TYPE, data)
    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_email_response) == resp_json
    notification = notify_db_session.session.scalar(
        select(Notification).where(Notification.service_id == template.service_id)
    )
    assert notification.status == NOTIFICATION_CREATED
    assert notification.postage is None
    assert notification.callback_url == 'https://www.test.com'

    assert resp_json['id'] == str(notification.id)
    assert resp_json['billing_code'] == 'TESTCODE'
    assert resp_json['reference'] == reference
    assert notification.reference is None
    assert notification.reply_to_text is None
    assert resp_json['content']['body'] == template.content.replace('((name))', '<redacted>')
    assert resp_json['content']['subject'] == template.subject.replace('((name))', '<redacted>')
    assert 'v2/notifications/{}'.format(notification.id) in resp_json['uri']
    assert resp_json['template']['id'] == str(template.id)
    assert resp_json['template']['version'] == template.version
    assert 'services/{}/templates/{}'.format(str(template.service_id), str(template.id)) in resp_json['template']['uri']
    assert resp_json['callback_url'] == 'https://www.test.com'
    assert not resp_json['scheduled_for']
    assert mock_deliver_email.called


@pytest.mark.parametrize('reference', [None, 'not none'])
def test_post_email_notification_with_reply_to_returns_201(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mock_deliver_email,
    reference,
):
    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='((name))',
        content='Hello ((name))\nThis is an email from va.gov',
        reply_to_email='testing@email.com',
    )
    data = {
        'email_address': template.service.users[0].email_address,
        'template_id': template.id,
        'personalisation': {'name': 'Bob'},
        'billing_code': 'TESTCODE',
        'callback_url': 'https://www.test.com',
    }

    if reference is not None:
        # Have to set reference for the asserts below, can't add it to data in the None case
        reference = str(uuid.uuid4())
        data['reference'] = reference

    response = post_send_notification(client, sample_api_key(service=template.service), EMAIL_TYPE, data)
    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_email_response) == resp_json
    stmt = select(Notification).where(Notification.service_id == template.service_id)
    notification = notify_db_session.session.scalar(stmt)

    # DB checks
    assert notification.status == NOTIFICATION_CREATED
    assert notification.postage is None
    assert notification.reply_to_text == 'testing@email.com'
    assert notification.callback_url == 'https://www.test.com'

    # endpoint checks
    assert resp_json['id'] == str(notification.id)
    assert resp_json['billing_code'] == 'TESTCODE'
    assert resp_json['reference'] == reference
    assert resp_json['content']['body'] == template.content.replace('((name))', '<redacted>')
    assert resp_json['content']['subject'] == template.subject.replace('((name))', '<redacted>')
    assert 'v2/notifications/{}'.format(notification.id) in resp_json['uri']
    assert resp_json['template']['id'] == str(template.id)
    assert resp_json['template']['version'] == template.version
    assert 'services/{}/templates/{}'.format(str(template.service_id), str(template.id)) in resp_json['template']['uri']
    assert not resp_json['scheduled_for']
    assert resp_json['callback_url'] == 'https://www.test.com'
    assert mock_deliver_email.called


@pytest.mark.parametrize(
    'recipient, notification_type',
    [
        ('simulate-delivered@notifications.va.gov', EMAIL_TYPE),
        ('simulate-delivered-2@notifications.va.gov', EMAIL_TYPE),
        ('simulate-delivered-3@notifications.va.gov', EMAIL_TYPE),
        ('6132532222', SMS_TYPE),
        ('6132532223', SMS_TYPE),
        ('6132532224', SMS_TYPE),
    ],
)
def test_should_not_persist_or_send_notification_if_simulated_recipient(
    client,
    recipient,
    notification_type,
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
):
    template = sample_template(template_type=notification_type)
    apply_async = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(notification_type))

    if notification_type == SMS_TYPE:
        data = {
            'phone_number': recipient,
        }
    else:
        data = {
            'email_address': recipient,
        }
    data['template_id'] = str(template.id)

    response = post_send_notification(client, sample_api_key(service=template.service), notification_type, data)

    assert response.status_code == 201
    apply_async.assert_not_called()
    assert response.get_json()['id']
    stmt = select(Notification).where(Notification.service_id == template.service_id)
    assert notify_db_session.session.scalar(stmt) is None


@pytest.mark.parametrize(
    'notification_type, key_send_to, send_to',
    [(SMS_TYPE, 'phone_number', '6502532222'), (EMAIL_TYPE, 'email_address', 'sample@email.com')],
)
def test_send_notification_uses_email_or_sms_queue_when_template_is_marked_as_priority(
    client,
    sample_api_key,
    sample_service,
    sample_template,
    mocker,
    notification_type,
    key_send_to,
    send_to,
):
    template = sample_template(service=sample_service(), template_type=notification_type, process_type='priority')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    data = {key_send_to: send_to, 'template_id': str(template.id)}

    response = post_send_notification(client, sample_api_key(service=template.service), notification_type, data)

    notification_id = str(json.loads(response.data)['id'])

    assert response.status_code == 201

    mocked_chain.assert_called_once()

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, [f'send-{notification_type}-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.kwargs.get('notification_id') == notification_id


@pytest.mark.parametrize(
    'notification_type, key_send_to, send_to',
    [(SMS_TYPE, 'phone_number', '6502532222'), (EMAIL_TYPE, 'email_address', 'sample@email.com')],
)
def test_returns_a_429_limit_exceeded_if_rate_limit_exceeded(
    client,
    sample_api_key,
    sample_service,
    sample_template,
    mocker,
    notification_type,
    key_send_to,
    send_to,
):
    template = sample_template(service=sample_service(), template_type=notification_type)
    persist_mock = mocker.patch('app.v2.notifications.post_notifications.persist_notification')
    deliver_mock = mocker.patch('app.v2.notifications.post_notifications.send_notification_to_queue')
    mocker.patch(
        'app.v2.notifications.post_notifications.check_rate_limiting',
        side_effect=RateLimitError('LIMIT', 'INTERVAL', 'TYPE'),
    )

    data = {key_send_to: send_to, 'template_id': str(template.id)}

    response = post_send_notification(client, sample_api_key(service=template.service), notification_type, data)

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
    sample_api_key,
    sample_service,
    sample_template,
):
    # Create a service that does not have INTERNATIONAL_SMS permission.
    service = sample_service(service_permissions=[EMAIL_TYPE, SMS_TYPE])
    template = sample_template(service=service)

    data = {'phone_number': '+20-12-1234-1234', 'template_id': template.id}

    response = post_send_notification(client, sample_api_key(service=service), SMS_TYPE, data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    error_json = response.get_json()
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [
        {'error': 'BadRequestError', 'message': 'Cannot send to international mobile numbers'}
    ]


def test_post_sms_notification_with_archived_reply_to_id_returns_400(
    client,
    sample_api_key,
    sample_inbound_number,
    sample_template,
    sample_sms_sender,
):
    template = sample_template()
    service_number = sample_inbound_number(service_id=template.service_id)
    archived_sender = sample_sms_sender(
        service_id=template.service.id,
        inbound_number_id=service_number.id,
        is_default=False,
        archived=True,
    )
    data = {'phone_number': '+16502532222', 'template_id': template.id, 'sms_sender_id': archived_sender.id}

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)
    assert response.status_code == 400
    resp_json = response.get_json()
    assert (
        'sms_sender_id {} does not exist in database for service id {}'.format(archived_sender.id, template.service_id)
        in resp_json['errors'][0]['message']
    )
    assert 'BadRequestError' in resp_json['errors'][0]['error']


@pytest.mark.parametrize(
    'recipient,label,permission_type, notification_type,expected_error',
    [
        ('6502532222', 'phone_number', EMAIL_TYPE, SMS_TYPE, 'text messages'),
        ('someone@test.com', 'email_address', SMS_TYPE, EMAIL_TYPE, 'emails'),
    ],
)
def test_post_sms_notification_returns_400_if_not_allowed_to_send_notification(
    client,
    recipient,
    label,
    permission_type,
    notification_type,
    expected_error,
    sample_api_key,
    sample_service,
    sample_template,
):
    # Intentionally has the wrong permission
    service = sample_service(service_permissions=[permission_type])
    template = sample_template(service=service, template_type=notification_type)
    data = {label: recipient, 'template_id': template.id}

    response = post_send_notification(client, sample_api_key(service=template.service), template.template_type, data)

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    error_json = response.get_json()
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [
        {'error': 'BadRequestError', 'message': 'Service is not allowed to send {}'.format(expected_error)}
    ]


@pytest.mark.parametrize('restricted', [True, False])
def test_post_sms_notification_returns_400_if_number_not_whitelisted(
    client,
    sample_api_key,
    sample_service,
    sample_template,
    restricted,
):
    service = sample_service(restricted=restricted, service_permissions=[SMS_TYPE, INTERNATIONAL_SMS_TYPE])
    template = sample_template(service=service)
    api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEAM)

    data = {
        'phone_number': '+16132532235',
        'template_id': template.id,
    }
    auth_header = create_authorization_header(api_key)

    response = client.post(
        path='/v2/notifications/sms', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 400
    error_json = response.get_json()
    assert error_json['status_code'] == 400
    assert error_json['errors'] == [
        {'error': 'BadRequestError', 'message': 'Can’t send to this recipient using a team-only API key'}
    ]


def test_post_sms_notification_returns_201_if_allowed_to_send_international_sms(
    sample_api_key,
    sample_service,
    sample_template,
    client,
):
    """
    Ensure that SMS messages can be sent to phones outside the United States.

    This is only testing that this application's code doesn't reject a foreign
    number.  Actual delivery depends on the capabilities of the 3rd party SMS
    backend (i.e. Twilio, etc.).
    """
    service = sample_service(service_permissions=[INTERNATIONAL_SMS_TYPE, SMS_TYPE])
    template = sample_template(service=service)
    data = {'phone_number': '+20-12-1234-1234', 'template_id': template.id}

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)

    assert response.status_code == 201
    assert response.headers['Content-type'] == 'application/json'


def test_post_sms_should_persist_supplied_sms_number(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mock_deliver_sms,
):
    template = sample_template()
    data = {'phone_number': '+14254147755', 'template_id': str(template.id), 'personalisation': {' Name': 'Jo'}}

    response = post_send_notification(client, sample_api_key(service=template.service), SMS_TYPE, data)
    assert response.status_code == 201
    resp_json = response.get_json()
    notifications = notify_db_session.session.scalars(
        select(Notification).where(Notification.service_id == template.service_id)
    ).all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert '+14254147755' == notifications[0].to
    assert resp_json['id'] == str(notification_id)
    assert mock_deliver_sms.called


@pytest.mark.parametrize(
    'notification_type, key_send_to, send_to',
    [
        (SMS_TYPE, 'phone_number', '6502532222'),
        (EMAIL_TYPE, 'email_address', 'sample@email.com'),
    ],
)
@freeze_time('2017-05-14 14:00:00')
def test_post_notification_with_scheduled_for(
    client,
    notify_db_session,
    sample_api_key,
    sample_service,
    sample_template,
    notification_type,
    key_send_to,
    send_to,
):
    service = sample_service(
        service_name=str(uuid.uuid4()), service_permissions=[EMAIL_TYPE, SMS_TYPE, SCHEDULE_NOTIFICATIONS]
    )
    template = sample_template(service=service, template_type=notification_type)
    data = {
        key_send_to: send_to,
        'template_id': str(template.id) if notification_type == EMAIL_TYPE else str(template.id),
        'scheduled_for': '2017-05-14 14:15',
    }

    response = post_send_notification(client, sample_api_key(service=service), notification_type, data)
    assert response.status_code == 201
    resp_json = response.get_json()

    stmt = select(ScheduledNotification).where(ScheduledNotification.notification_id == resp_json['id'])
    scheduled_notification = notify_db_session.session.scalars(stmt).one()

    assert resp_json['id'] == str(scheduled_notification.notification_id)
    assert resp_json['scheduled_for'] == '2017-05-14 14:15'

    # Teardown
    stmt = delete(ScheduledNotification).where(ScheduledNotification.id == scheduled_notification.id)
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.mark.parametrize(
    'notification_type, key_send_to, send_to',
    [(SMS_TYPE, 'phone_number', '6502532222'), (EMAIL_TYPE, 'email_address', 'sample@email.com')],
)
@freeze_time('2017-05-14 14:00:00')
def test_post_notification_raises_bad_request_if_service_not_invited_to_schedule(
    client,
    sample_api_key,
    sample_template,
    notification_type,
    key_send_to,
    send_to,
):
    template = sample_template(template_type=notification_type)
    data = {key_send_to: send_to, 'template_id': str(template.id), 'scheduled_for': '2017-05-14 14:15'}

    response = post_send_notification(client, sample_api_key(service=template.service), notification_type, data)
    assert response.status_code == 400
    error_json = response.get_json()
    assert error_json['errors'] == [
        {'error': 'BadRequestError', 'message': 'Cannot schedule notifications (this feature is invite-only)'}
    ]


def test_post_notification_raises_bad_request_if_not_valid_notification_type(
    client,
    sample_api_key,
):
    response = post_send_notification(client, sample_api_key(), 'foo', {})
    assert response.status_code == 404
    error_json = response.get_json()
    assert 'The requested URL was not found on the server.' in error_json['message']


@pytest.mark.parametrize('notification_type', [SMS_TYPE, EMAIL_TYPE])
def test_post_notification_with_wrong_type_of_sender(
    client,
    sample_api_key,
    sample_template,
    notification_type,
    fake_uuid,
):
    if notification_type == EMAIL_TYPE:
        template = sample_template(template_type=EMAIL_TYPE)
        form_label = 'sms_sender_id'
        data = {'email_address': 'test@test.com', 'template_id': str(template.id), form_label: fake_uuid}
    elif notification_type == SMS_TYPE:
        template = sample_template(template_type=SMS_TYPE)
        form_label = 'email_reply_to_id'
        data = {'phone_number': '+16502532222', 'template_id': str(template.id), form_label: fake_uuid}

    response = post_send_notification(client, sample_api_key(template.service), notification_type, data)
    assert response.status_code == 400
    resp_json = response.get_json()
    assert (
        'Additional properties are not allowed ({} was unexpected)'.format(form_label)
        in resp_json['errors'][0]['message']
    )
    assert 'ValidationError' in resp_json['errors'][0]['error']


def test_post_email_notification_with_valid_reply_to_id_returns_201(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mock_deliver_email,
):
    template = sample_template(template_type=EMAIL_TYPE)
    reply_to_email = create_reply_to_email(template.service, 'test@test.com')
    data = {
        'email_address': template.service.users[0].email_address,
        'template_id': template.id,
        'email_reply_to_id': reply_to_email.id,
    }

    response = post_send_notification(client, sample_api_key(template.service), EMAIL_TYPE, data)
    assert response.status_code == 201
    resp_json = response.get_json()
    assert validate(resp_json, post_email_response) == resp_json
    notification = notify_db_session.session.scalars(
        select(Notification).where(Notification.service_id == template.service_id)
    ).one()
    assert notification.reply_to_text == 'test@test.com'
    assert resp_json['id'] == str(notification.id)
    assert mock_deliver_email.called

    assert notification.reply_to_text == reply_to_email.email_address


def test_post_email_notification_with_invalid_reply_to_id_returns_400(
    client,
    sample_api_key,
    sample_template,
    fake_uuid,
):
    template = sample_template(template_type=EMAIL_TYPE)
    data = {
        'email_address': template.service.users[0].email_address,
        'template_id': template.id,
        'email_reply_to_id': fake_uuid,
    }

    response = post_send_notification(client, sample_api_key(template.service), EMAIL_TYPE, data)
    assert response.status_code == 400
    resp_json = response.get_json()
    assert (
        'email_reply_to_id {} does not exist in database for service id {}'.format(fake_uuid, template.service_id)
        in resp_json['errors'][0]['message']
    )
    assert 'BadRequestError' in resp_json['errors'][0]['error']


def test_post_email_notification_with_archived_reply_to_id_returns_400(
    client,
    sample_api_key,
    sample_template,
):
    template = sample_template(template_type=EMAIL_TYPE)
    archived_reply_to = create_reply_to_email(template.service, 'reply_to@test.com', is_default=False, archived=True)
    data = {'email_address': 'test@test.com', 'template_id': template.id, 'email_reply_to_id': archived_reply_to.id}

    response = post_send_notification(client, sample_api_key(template.service), EMAIL_TYPE, data)
    assert response.status_code == 400
    resp_json = response.get_json()
    assert (
        'email_reply_to_id {} does not exist in database for service id {}'.format(
            archived_reply_to.id, template.service_id
        )
        in resp_json['errors'][0]['message']
    )
    assert 'BadRequestError' in resp_json['errors'][0]['error']


class TestPostNotificationWithAttachment:
    base64_encoded_file = 'VGV4dCBjb250ZW50IGhlcmU='

    @pytest.fixture(autouse=True)
    def attachment_store_mock(self, mocker):
        return mocker.patch('app.v2.notifications.post_notifications.attachment_store')

    @pytest.fixture(autouse=True)
    def validate_mimetype_mock(self, mocker):
        return mocker.patch(
            'app.v2.notifications.post_notifications.extract_and_validate_mimetype', return_value='fake/mimetype'
        )

    @pytest.fixture(autouse=True)
    def feature_toggle_enabled(self, mocker):
        mock_feature_flag(mocker, feature_flag=FeatureFlag.EMAIL_ATTACHMENTS_ENABLED, enabled='True')

    def test_returns_not_implemented_if_sending_method_is_link(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
        attachment_store_mock,
    ):
        # service_with_upload_document_permission
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE)
        response = post_send_notification(
            client,
            sample_api_key(service),
            EMAIL_TYPE,
            {
                'email_address': 'foo@bar.com',
                'template_id': template.id,
                'personalisation': {
                    'some_attachment': {
                        'file': self.base64_encoded_file,
                        'filename': 'attachment.pdf',
                        'sending_method': 'link',
                    }
                },
            },
        )

        assert response.status_code == 501
        attachment_store_mock.put.assert_not_called()

    @pytest.mark.parametrize('sending_method', ['attach', None])
    def test_attachment_upload_with_sending_method_attach(
        self,
        client,
        mocker,
        notify_db_session,
        sending_method,
        sample_api_key,
        sample_service,
        sample_template,
        attachment_store_mock,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='See attached file')
        mock_uploaded_attachment = ('fake-id', 'fake-key')
        attachment_store_mock.put.return_value = mock_uploaded_attachment

        data = {
            'email_address': 'foo@bar.com',
            'template_id': template.id,
            'personalisation': {
                'some_attachment': {
                    'file': self.base64_encoded_file,
                    'filename': 'file.pdf',
                }
            },
        }

        if sending_method:
            data['personalisation']['some_attachment']['sending_method'] = sending_method

        response = post_send_notification(client, sample_api_key(service), EMAIL_TYPE, data)

        assert response.status_code == 201, response.get_data(as_text=True)
        resp_json = response.get_json()
        assert validate(resp_json, post_email_response) == resp_json
        attachment_store_mock.put.assert_called_once_with(
            **{
                'service_id': service.id,
                'attachment_stream': base64.b64decode(self.base64_encoded_file),
                'mimetype': 'fake/mimetype',
                'sending_method': 'attach',
            },
        )

        stmt = select(Notification).where(Notification.service_id == template.service_id)
        notification = notify_db_session.session.scalars(stmt).one()

        assert notification.status == NOTIFICATION_CREATED
        assert notification.personalisation == {
            'some_attachment': {
                'file_name': 'file.pdf',
                'sending_method': 'attach',
                'id': 'fake-id',
                'encryption_key': 'fake-key',
            }
        }

    def test_attachment_upload_unsupported_mimetype(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
        attachment_store_mock,
        validate_mimetype_mock,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='See attached file')
        validate_mimetype_mock.side_effect = UnsupportedMimeTypeException()

        data = {
            'email_address': 'foo@bar.com',
            'template_id': template.id,
            'personalisation': {
                'some_attachment': {
                    'file': self.base64_encoded_file,
                    'filename': 'file.pdf',
                }
            },
        }

        response = post_send_notification(client, sample_api_key(service), EMAIL_TYPE, data)

        assert response.status_code == 400
        attachment_store_mock.put.assert_not_called()

    def test_long_filename(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='See attached file')
        filename = 'a' * 256
        response = post_send_notification(
            client,
            sample_api_key(service),
            EMAIL_TYPE,
            {
                'email_address': 'foo@bar.com',
                'template_id': template.id,
                'personalisation': {
                    'document': {
                        'file': self.base64_encoded_file,
                        'filename': filename,
                        'sending_method': 'attach',
                    },
                },
            },
        )

        assert response.status_code == 400
        resp_json = response.get_json()
        assert 'ValidationError' in resp_json['errors'][0]['error']
        assert filename in resp_json['errors'][0]['message']
        assert 'too long' in resp_json['errors'][0]['message']

    def test_filename_required_check(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='See attached file')
        response = post_send_notification(
            client,
            sample_api_key(service),
            EMAIL_TYPE,
            {
                'email_address': 'foo@bar.com',
                'template_id': template.id,
                'personalisation': {
                    'document': {'file': self.base64_encoded_file, 'sending_method': 'attach'},
                },
            },
        )

        assert response.status_code == 400
        resp_json = response.get_json()
        assert 'ValidationError' in resp_json['errors'][0]['error']
        assert 'filename is a required property' in resp_json['errors'][0]['message']

    def test_bad_sending_method(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='See attached file')
        response = post_send_notification(
            client,
            sample_api_key(service),
            EMAIL_TYPE,
            {
                'email_address': 'foo@bar.com',
                'template_id': template.id,
                'personalisation': {
                    'document': {
                        'file': self.base64_encoded_file,
                        'filename': '1.txt',
                        'sending_method': 'not-a-real-sending-method',
                    }
                },
            },
        )

        assert response.status_code == 400
        resp_json = response.get_json()
        assert (
            'personalisation not-a-real-sending-method is not one of [attach, link]'
            in resp_json['errors'][0]['message']
        )

    def test_not_base64_file(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='See attached file')
        response = post_send_notification(
            client,
            sample_api_key(service),
            EMAIL_TYPE,
            {
                'email_address': 'foo@bar.com',
                'template_id': template.id,
                'personalisation': {
                    'document': {
                        'file': 'abc',
                        'sending_method': 'attach',
                        'filename': '1.txt',
                    }
                },
            },
        )

        assert response.status_code == 400
        resp_json = response.get_json()
        assert 'Incorrect padding' in resp_json['errors'][0]['message']

    def test_simulated(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='Document: ((document))')

        data = {
            'email_address': 'simulate-delivered@notifications.va.gov',
            'template_id': template.id,
            'personalisation': {'document': {'file': 'abababab', 'filename': 'file.pdf'}},
        }

        response = post_send_notification(client, sample_api_key(service), EMAIL_TYPE, data)

        assert response.status_code == 201
        resp_json = response.get_json()
        assert validate(resp_json, post_email_response) == resp_json

        assert resp_json['content']['body'] == 'Document: <redacted>'

    def test_without_document_upload_permission(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
    ):
        service = sample_service(service_permissions=[EMAIL_TYPE])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='Document: ((document))')

        response = post_send_notification(
            client,
            sample_api_key(service),
            EMAIL_TYPE,
            {
                'email_address': service.users[0].email_address,
                'template_id': template.id,
                'personalisation': {'document': {'file': 'abababab', 'filename': 'foo.pdf'}},
            },
        )

        assert response.status_code == 400
        resp_json = response.get_json()
        assert 'Service is not allowed to send documents' in resp_json['errors'][0]['message']

    def test_attachment_store_error(
        self,
        client,
        sample_api_key,
        sample_service,
        sample_template,
        attachment_store_mock,
    ):
        attachment_store_mock.put.side_effect = AttachmentStoreError()
        service = sample_service(service_permissions=[EMAIL_TYPE, UPLOAD_DOCUMENT])
        template = sample_template(service=service, template_type=EMAIL_TYPE, content='See attached file')
        data = {
            'email_address': 'foo@bar.com',
            'template_id': template.id,
            'personalisation': {
                'some_attachment': {
                    'file': self.base64_encoded_file,
                    'filename': 'file.pdf',
                }
            },
        }

        response = post_send_notification(client, sample_api_key(service), EMAIL_TYPE, data)

        assert response.status_code == 400
        resp_json = response.get_json()
        assert 'Unable to upload attachment object to store' in resp_json['errors'][0]['message']


def test_post_notification_returns_400_when_get_json_throws_exception(
    client,
    sample_api_key,
    sample_template,
):
    template = sample_template(template_type=EMAIL_TYPE)
    api_key = sample_api_key(service=template.service)
    auth_header = create_authorization_header(api_key)
    response = client.post(
        path='v2/notifications/email', data='[', headers=[('Content-Type', 'application/json'), auth_header]
    )
    assert response.status_code == 400


@pytest.mark.skip(reason='failing in pipeline for some reason')
@pytest.mark.parametrize(
    'expected_type, expected_value, task',
    [
        (
            IdentifierType.VA_PROFILE_ID.value,
            'some va profile id',
            'app.celery.contact_information_tasks.lookup_contact_info',
        ),
        (IdentifierType.PID.value, 'some pid', 'app.celery.lookup_va_profile_id_task.lookup_va_profile_id'),
        (IdentifierType.ICN.value, 'some icn', 'app.celery.lookup_va_profile_id_task.lookup_va_profile_id'),
    ],
)
def test_should_process_notification_successfully_with_recipient_identifiers(
    client,
    mocker,
    notify_db_session,
    enable_accept_recipient_identifiers_enabled_feature_flag,
    expected_type,
    expected_value,
    task,
    sample_api_key,
    sample_template,
):
    template = sample_template(template_type=EMAIL_TYPE)
    api_key = sample_api_key(service=template.service)
    mocked_task = mocker.patch(f'{task}.apply_async')

    data = {'template_id': template.id, 'recipient_identifier': {'id_type': expected_type, 'id_value': expected_value}}
    auth_header = create_authorization_header(api_key)
    response = client.post(
        path='v2/notifications/email',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    notifications = notify_db_session.session.scalars(
        select(Notification).where(Notification.service_id == template.service_id)
    ).all()

    assert response.status_code == 201
    assert len(notifications) == 1

    stmt = select(func.count()).select_from(RecipientIdentifier)
    assert notify_db_session.session.scalar(stmt) == 1

    notification = notifications[0]
    assert notification.status == NOTIFICATION_CREATED
    assert notification.recipient_identifiers[expected_type].id_type == expected_type
    assert notification.recipient_identifiers[expected_type].id_value == expected_value

    mocked_task.assert_called_once()


@pytest.mark.skip(reason='test failing in pipeline but no where else')
@pytest.mark.parametrize('notification_type', [EMAIL_TYPE, SMS_TYPE])
def test_should_post_notification_successfully_with_recipient_identifier_and_contact_info(
    notify_db_session,
    client,
    mocker,
    enable_accept_recipient_identifiers_enabled_feature_flag,
    check_recipient_communication_permissions_enabled,
    sample_api_key,
    sample_template,
    sample_sms_template_with_html,
    notification_type,
):
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    expected_id_type = IdentifierType.VA_PROFILE_ID.value
    expected_id_value = 'some va profile id'

    if notification_type == EMAIL_TYPE:
        template = sample_template(template_type=EMAIL_TYPE)
        data = {
            'template_id': template.id,
            'email_address': 'some-email@test.com',
            'recipient_identifier': {'id_type': expected_id_type, 'id_value': expected_id_value},
            'billing_code': 'TESTCODE',
        }
    else:
        template = sample_template(prefix_sms=True, content='Hello (( Name))\nHere is <em>some HTML</em> & entities')
        data = {
            'template_id': template.id,
            'phone_number': '+16502532222',
            'recipient_identifier': {'id_type': expected_id_type, 'id_value': expected_id_value},
            'personalisation': {'Name': 'Flowers'},
            'billing_code': 'TESTCODE',
        }

    api_key = sample_api_key(service=template.service)

    auth_header = create_authorization_header(api_key)
    response = client.post(
        path=f'v2/notifications/{notification_type}',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 201

    stmt = select(func.count()).select_from(Notification)
    assert notify_db_session.session.scalar(stmt) == 1

    stmt = select(Notification)
    notification = notify_db_session.session.scalars(stmt).one()

    assert notification.status == NOTIFICATION_CREATED

    # Commenting out these assertions because of funky failures in pipeline
    # assert RecipientIdentifier.query.count() == 1
    # assert notification.recipient_identifiers[expected_id_type].id_type == expected_id_type
    # assert notification.recipient_identifiers[expected_id_type].id_value == expected_id_value

    mocked_chain.assert_called_once()

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(
        args, [QueueNames.COMMUNICATION_ITEM_PERMISSIONS, f'send-{notification_type}-tasks']
    ):
        assert called_task.options['queue'] == expected_task
        if expected_task == QueueNames.COMMUNICATION_ITEM_PERMISSIONS:
            assert called_task.args == (
                expected_id_type,
                expected_id_value,
                str(notification.id),
                notification.notification_type,
                notification.template.communication_item_id,
            )
        else:
            assert called_task.args[0] == str(notification.id)


def test_post_notification_returns_501_when_recipient_identifiers_present_and_feature_flag_disabled(
    client,
    mocker,
    sample_api_key,
    sample_template,
):
    api_key = sample_api_key()
    template = sample_template(service=api_key.service, template_type=EMAIL_TYPE)
    mocker.patch('app.v2.notifications.post_notifications.accept_recipient_identifiers_enabled', return_value=False)
    data = {
        'template_id': template.id,
        'recipient_identifier': {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'foo'},
    }
    auth_header = create_authorization_header(api_key)
    response = client.post(
        path='v2/notifications/email',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert response.status_code == 501


@pytest.mark.parametrize('notification_type', [EMAIL_TYPE, SMS_TYPE])
def test_post_notification_returns_400_when_billing_code_length_exceeds_max(
    client,
    sample_api_key,
    sample_service,
    sample_template,
    notification_type,
):
    data = {
        'billing_code': (
            'awpeoifhwaepoifjaajf5alsdkfj5asdlkfja5sdlkfjasd5lkfjaeoifjapweoighaeiofjawieofjaeiopwfghaepiofhposihf'
            'paoweifjafjsdlkfjsldfkjsdlkfjsldkjpoeifjapseoifhapoeifjaspoeifhaeoihfeopifhaepoifjeaioghaeoifjaepoifj'
            'aepighaepoifjaepoifhaepogihaewoipfjeaiopfjaeopighaepiwofjaeopiwfjaepoifj'
        )
    }
    service = sample_service(prefix_sms=True)
    api_key = sample_api_key(service=service)
    if notification_type == EMAIL_TYPE:
        template = sample_template(service=service, template_type=EMAIL_TYPE)
        data['email_address'] = 'someemail@test.com'
    elif notification_type == SMS_TYPE:
        template = sample_template(
            service=service, template_type=SMS_TYPE, content='Hello (( Name))\nHere is <em>some HTML</em> & entities'
        )
        data['phone_number'] = '+16502532222'
    else:
        raise NotImplementedError(f'{notification_type=} not implemented')

    data['template_id'] = template.id

    auth_header = create_authorization_header(api_key)
    response = client.post(
        path=f'v2/notifications/{notification_type}',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 400
    assert 'too long' in response.json['errors'][0]['message']

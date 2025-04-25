import random
import string
from uuid import uuid4

import pytest
from flask import json
from freezegun import freeze_time
from notifications_python_client.authentication import create_jwt_token
from notifications_utils import SMS_CHAR_COUNT_LIMIT

import app
from app.constants import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    SMS_TYPE,
)
from app.dao.templates_dao import dao_update_template
from app.errors import InvalidRequest
from app.models import (
    Notification,
    Template,
)
from app.v2.errors import TooManyRequestsError
from tests import create_authorization_header


def test_should_reject_bad_phone_numbers(
    notify_api,
    sample_api_key,
    sample_template,
    mocker,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
            template = sample_template()

            data = {
                'to': 'invalid',
                'template': template.id,
                'sms_sender_id': str(uuid4()),
            }
            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.post(
                path='/notifications/sms',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert response.status_code == 400
            mocked.assert_not_called()
            json_resp = response.get_json()
            assert json_resp['result'] == 'error'
            assert len(json_resp['message'].keys()) == 1
            assert 'Invalid phone number: Phone numbers must not contain letters' in json_resp['message']['to']


def test_should_not_send_notification_for_archived_template(
    notify_api,
    sample_api_key,
    sample_template,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            template = sample_template()
            template.archived = True
            dao_update_template(template)

            json_data = json.dumps(
                {
                    'to': '+16502532222',
                    'template': template.id,
                    'sms_sender_id': str(uuid4()),
                }
            )
            auth_header = create_authorization_header(sample_api_key(service=template.service))

            resp = client.post(
                path='/notifications/sms', data=json_data, headers=[('Content-Type', 'application/json'), auth_header]
            )
            assert resp.status_code == 400
            json_resp = resp.get_json()
            assert 'Template has been deleted' in json_resp['message']


def test_should_reject_email_notification_with_bad_email(
    notify_api,
    sample_api_key,
    sample_template,
    mocker,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
            template = sample_template(template_type=EMAIL_TYPE)
            to_address = 'bad-email'

            data = {'to': to_address, 'template': str(template.service_id)}
            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.post(
                path='/notifications/email',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            data = json.loads(response.get_data(as_text=True))
            mocked.apply_async.assert_not_called()
            assert response.status_code == 400
            assert data['result'] == 'error'
            assert data['message']['to'][0] == 'Not a valid email address'


@freeze_time('2016-01-01 12:00:00.061258')
def test_should_block_api_call_if_over_day_limit_for_live_service(
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
    notify_api,
    mocker,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocker.patch(
                'app.notifications.validators.check_service_over_daily_message_limit',
                side_effect=TooManyRequestsError(1),
            )
            mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
            service = sample_service(message_limit=1)
            api_key = sample_api_key(service=service)
            email_template = sample_template(service=service, template_type=EMAIL_TYPE)
            sample_notification(template=email_template, api_key=api_key)

            data = {'to': 'ok@ok.com', 'template': str(email_template.id)}

            auth_header = create_authorization_header(api_key)

            response = client.post(
                path='/notifications/email',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            json.loads(response.get_data(as_text=True))
            assert response.status_code == 429


@freeze_time('2016-01-01 12:00:00.061258')
def test_should_block_api_call_if_over_day_limit_for_restricted_service(
    notify_api,
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
    mocker,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
            mocker.patch(
                'app.notifications.validators.check_service_over_daily_message_limit',
                side_effect=TooManyRequestsError(1),
            )
            service = sample_service(restricted=True, message_limit=1)
            api_key = sample_api_key(service=service)
            email_template = sample_template(service=service, template_type=EMAIL_TYPE)
            sample_notification(template=email_template, api_key=api_key)

            data = {'to': 'ok@ok.com', 'template': str(email_template.id)}

            auth_header = create_authorization_header(api_key)

            response = client.post(
                path='/notifications/email',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            json.loads(response.get_data(as_text=True))

            assert response.status_code == 429


def test_should_not_send_email_if_team_api_key_and_not_a_service_user(
    notify_api,
    sample_api_key,
    sample_template,
    mocker,
):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
        template = sample_template(template_type=EMAIL_TYPE)

        data = {
            'to': 'not-someone-we-trust@email-address.com',
            'template': str(template.id),
        }

        auth_header = create_authorization_header(sample_api_key(service=template.service, key_type=KEY_TYPE_TEAM))

        response = client.post(
            path='/notifications/email',
            data=json.dumps(data),
            headers=[('Content-Type', 'application/json'), auth_header],
        )

        json_resp = json.loads(response.get_data(as_text=True))

        app.celery.provider_tasks.deliver_email.apply_async.assert_not_called()

        assert response.status_code == 400
        assert ['Can’t send to this recipient using a team-only API key'] == json_resp['message']['to']


def test_should_not_send_sms_if_team_api_key_and_not_a_service_user(
    notify_api,
    sample_api_key,
    sample_template,
    mocker,
    sample_sms_sender,
):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
        template = sample_template()

        data = {
            'to': '6502532229',
            'template': str(template.id),
            'sms_sender_id': str(sample_sms_sender(service_id=template.service.id).id),
        }

        auth_header = create_authorization_header(sample_api_key(service=template.service, key_type=KEY_TYPE_TEAM))

        response = client.post(
            path='/notifications/sms',
            data=json.dumps(data),
            headers=[('Content-Type', 'application/json'), auth_header],
        )

        assert response.status_code == 400
        app.celery.provider_tasks.deliver_sms.apply_async.assert_not_called()
        json_resp = response.get_json()
        assert json_resp['message']['to'] == ['Can’t send to this recipient using a team-only API key']


@pytest.mark.parametrize('restricted', [True, False])
@pytest.mark.parametrize('limit', [0, 1])
def test_should_send_email_to_anyone_with_test_key(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
    restricted,
    limit,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    template = sample_template(template_type=EMAIL_TYPE)
    api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEST)
    data = {'to': f'anyone{uuid4()}@example.com', 'template': template.id}
    template.service.restricted = restricted
    template.service.message_limit = limit

    auth_header = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))

    response = client.post(
        path='/notifications/email',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), ('Authorization', 'Bearer {}'.format(auth_header))],
    )

    assert response.status_code == 201

    mocked.assert_called_once()

    result_notification_id, result_queue = mocked.call_args
    assert result_notification_id[1].get('notification_id') is not None
    assert result_queue['queue'] == 'notify-internal-tasks'

    # Teardown
    notification = notify_db_session.session.get(Notification, response.get_json()['data']['notification']['id'])
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


def test_create_template_raises_invalid_request_exception_with_missing_personalisation(
    notify_db_session,
    sample_template,
):
    from app.notifications.rest import create_template_object_for_notification

    template = sample_template(content='Hello (( Name))\nYour thing is due soon')

    with pytest.raises(InvalidRequest) as e:
        create_template_object_for_notification(template, {})
    assert {'template': ['Missing personalisation:  Name']} == e.value.message


def test_create_template_doesnt_raise_with_too_much_personalisation(
    notify_db_session,
    sample_template,
):
    from app.notifications.rest import create_template_object_for_notification

    template = sample_template(content='Hello (( Name))\nYour thing is due soon')
    create_template_object_for_notification(template, {'name': 'Jo', 'extra': 'stuff'})


@pytest.mark.parametrize('template_type, should_error', [(SMS_TYPE, True), (EMAIL_TYPE, False)])
def test_create_template_raises_invalid_request_when_content_too_large(
    notify_db_session,
    sample_template,
    template_type,
    should_error,
):
    sample = sample_template(template_type=template_type, content='((long_text))')
    template = notify_db_session.session.get(Template, sample.id)
    from app.notifications.rest import create_template_object_for_notification

    try:
        create_template_object_for_notification(
            template,
            {
                'long_text': ''.join(
                    random.choice(string.ascii_uppercase + string.digits)  # nosec
                    for _ in range(SMS_CHAR_COUNT_LIMIT + 1)
                )
            },
        )
        if should_error:
            pytest.fail('expected an InvalidRequest')
    except InvalidRequest as e:
        if not should_error:
            pytest.fail('do not expect an InvalidRequest')
        assert e.message == {
            'content': ['Content has a character count greater than the limit of {}'.format(SMS_CHAR_COUNT_LIMIT)]
        }


def test_should_not_allow_international_number_on_sms_notification(
    client,
    sample_api_key,
    sample_service,
    sample_template,
    mocker,
    sample_sms_sender,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    service = sample_service(service_permissions=[EMAIL_TYPE, SMS_TYPE])
    assert not service.has_permissions(INTERNATIONAL_SMS_TYPE)
    template = sample_template(service=service)
    assert template.service.id == service.id

    data = {
        'to': '+20-12-1234-1234',
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender(service_id=service.id).id),
    }

    auth_header = create_authorization_header(sample_api_key(service=service))

    response = client.post(
        path='/notifications/sms', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    mocked.assert_not_called()
    assert response.status_code == 400
    error_json = response.get_json()
    assert error_json['result'] == 'error'
    assert error_json['message']['to'][0] == 'Cannot send to international mobile numbers'


def test_should_not_allow_sms_notifications_if_service_permission_not_set(
    client,
    mocker,
    sample_api_key,
    sample_service,
    sample_sms_sender,
    sample_template,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    service = sample_service(service_permissions=[EMAIL_TYPE], check_if_service_exists=True)
    template = sample_template(service=service)

    data = {
        'to': '+16502532222',
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender(service_id=service.id).id),
    }

    auth_header = create_authorization_header(sample_api_key(service=service))

    response = client.post(
        path='/notifications/sms', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    mocked.assert_not_called()
    assert response.status_code == 400

    error_json = response.get_json()
    assert error_json['result'] == 'error'
    assert error_json['message']['service'][0] == 'Cannot send text messages'


def test_should_not_allow_email_notifications_if_service_permission_not_set(
    client,
    mocker,
    sample_api_key,
    sample_service,
    sample_template,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    service = sample_service(service_permissions=[SMS_TYPE])
    template = sample_template(service=service, template_type=EMAIL_TYPE)

    data = {'to': 'notify@digital.cabinet-office.gov.uk', 'template': str(template.id)}

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.post(
        path='/notifications/email', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    mocked.assert_not_called()
    assert response.status_code == 400
    error_json = json.loads(response.get_data(as_text=True))

    assert error_json['result'] == 'error'
    assert error_json['message']['service'][0] == 'Cannot send emails'

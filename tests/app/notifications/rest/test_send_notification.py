import random
import string
from uuid import uuid4

import pytest
from flask import json
from freezegun import freeze_time
from notifications_python_client.authentication import create_jwt_token
from notifications_utils import SMS_CHAR_COUNT_LIMIT

import app
from app.dao import notifications_dao
from app.dao.services_dao import dao_update_service
from app.dao.templates_dao import dao_get_all_templates_for_service, dao_update_template
from app.errors import InvalidRequest
from app.models import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    SMS_TYPE,
    Notification,
    NotificationHistory,
    Template,
)
from app.v2.errors import RateLimitError, TooManyRequestsError
from tests import create_authorization_header


@pytest.mark.parametrize('template_type', [SMS_TYPE, EMAIL_TYPE])
def test_create_notification_should_reject_if_missing_required_fields(
    notify_api,
    sample_api_key,
    mocker,
    template_type,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(template_type))
            auth_header = create_authorization_header(sample_api_key())

            response = client.post(
                path='/notifications/{}'.format(template_type),
                data='{}',
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert response.status_code == 400
            mocked.assert_not_called()
            json_resp = response.get_json()
            assert json_resp['result'] == 'error'
            assert 'Missing data for required field.' in json_resp['message']['to'][0]
            assert 'Missing data for required field.' in json_resp['message']['template'][0]


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
            assert 'Invalid phone number: Not a valid number' in json_resp['message']['to']


@pytest.mark.parametrize('template_type, to', [(SMS_TYPE, '+16502532222'), (EMAIL_TYPE, 'ok@ok.com')])
def test_send_notification_invalid_template_id(
    notify_api,
    sample_api_key,
    sample_service,
    mocker,
    template_type,
    to,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(template_type))
            mocked_uuid = str(uuid4())

            data = {
                'to': to,
                'template': mocked_uuid,
                'sms_sender_id': mocked_uuid,
            }
            auth_header = create_authorization_header(sample_api_key(service=sample_service()))

            response = client.post(
                path='/notifications/{}'.format(template_type),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert response.status_code == 404
            mocked.assert_not_called()
            json_resp = response.get_json()
            test_string = 'No result found'
            assert test_string in json_resp['message']


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


@pytest.mark.parametrize(
    'template_type, to', [(SMS_TYPE, '+16502532223'), (EMAIL_TYPE, 'not-someone-we-trust@email-address.com')]
)
def test_should_not_send_notification_if_restricted_and_not_a_service_user(
    notify_api,
    sample_api_key,
    sample_template,
    mocker,
    template_type,
    to,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(template_type))
            template = sample_template(template_type=template_type)
            template.service.restricted = True
            dao_update_service(template.service)

            data = {
                'to': to,
                'template': template.id,
                'sms_sender_id': str(uuid4()),
            }

            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.post(
                path='/notifications/{}'.format(template_type),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert response.status_code == 400
            json_resp = response.get_json()
            mocked.assert_not_called()
            assert json_resp['message']['to'] == [
                (
                    'Can’t send to this recipient when service is in trial mode '
                    '– see https://www.notifications.service.gov.uk/trial-mode'
                )
            ]


@pytest.mark.parametrize('template_type', [SMS_TYPE, EMAIL_TYPE])
def test_should_not_allow_template_from_another_service(
    notify_api,
    sample_api_key,
    sample_service,
    sample_template,
    sample_user,
    mocker,
    template_type,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(template_type))
            user = sample_user()
            service_1 = sample_service(user=user)
            service_2 = sample_service(user=user)
            sample_template(service=service_2, template_type=template_type)

            service_2_templates = dao_get_all_templates_for_service(service_id=service_2.id)
            to = user.mobile_number if template_type == SMS_TYPE else user.email_address
            data = {
                'to': to,
                'template': service_2_templates[0].id,
                'sms_sender_id': str(uuid4()),
            }

            auth_header = create_authorization_header(sample_api_key(service=service_1))

            response = client.post(
                path='/notifications/{}'.format(template_type),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            json_resp = response.get_json()
            mocked.assert_not_called()
            assert response.status_code == 404
            test_string = 'No result found'
            assert test_string in json_resp['message']


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
    mocked_uuid = str(uuid4())
    mocker.patch('app.notifications.process_notifications.uuid.uuid4', return_value=mocked_uuid)

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
    result_id, *rest = result_notification_id[0]
    assert result_id == mocked_uuid
    assert result_queue['queue'] == 'research-mode-tasks'

    # Teardown
    notification = notify_db_session.session.get(Notification, response.get_json()['data']['notification']['id'])
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


@pytest.mark.parametrize('key_type', [KEY_TYPE_NORMAL, KEY_TYPE_TEAM])
@pytest.mark.parametrize(
    'notification_type, to', [(SMS_TYPE, '6502532229'), (EMAIL_TYPE, 'non_whitelist_recipient@mail.com')]
)
def test_should_not_send_notification_to_non_whitelist_recipient_in_trial_mode(
    client,
    sample_api_key,
    sample_notification,
    sample_service_whitelist,
    sample_template,
    notification_type,
    to,
    key_type,
    mocker,
    sample_sms_sender,
):
    template = sample_template(template_type=notification_type)
    service = template.service
    sample_service_whitelist(service)
    service.restricted = True
    service.message_limit = 2
    api_key = sample_api_key(service=service, key_type=key_type)

    apply_async = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(notification_type))

    assert to not in [member.recipient for member in service.whitelist]

    sample_notification(template=template, api_key=api_key)

    data = {
        'to': to,
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender(service_id=service.id).id),
    }

    auth_header = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))

    response = client.post(
        path='/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), ('Authorization', 'Bearer {}'.format(auth_header))],
    )

    assert response.status_code == 400
    expected_response_message = (
        (
            'Can’t send to this recipient when service is in trial mode '
            '– see https://www.notifications.service.gov.uk/trial-mode'
        )
        if key_type == KEY_TYPE_NORMAL
        else ('Can’t send to this recipient using a team-only API key')
    )

    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert expected_response_message in json_resp['message']['to']
    apply_async.assert_not_called()


@pytest.mark.parametrize(
    'notification_type, template_type, to',
    [(EMAIL_TYPE, SMS_TYPE, 'notify@va.gov'), (SMS_TYPE, EMAIL_TYPE, '+16502532222')],
)
def test_should_error_if_notification_type_does_not_match_template_type(
    client,
    sample_api_key,
    sample_template,
    template_type,
    notification_type,
    to,
    sample_sms_sender,
):
    template = sample_template(template_type=template_type)
    data = {
        'to': to,
        'template': template.id,
        'sms_sender_id': str(sample_sms_sender(service_id=template.service.id).id),
    }
    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.post(
        '/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 400
    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert (
        '{0} template is not suitable for {1} notification'.format(template_type, notification_type)
        in json_resp['message']
    )


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


@pytest.mark.parametrize(
    'notification_type, err_msg',
    [
        ('letter', 'letter notification type is not supported, please use the latest version of the client'),
        ('apple', 'apple notification type is not supported'),
    ],
)
def test_should_throw_exception_if_notification_type_is_invalid(
    client,
    sample_api_key,
    notification_type,
    err_msg,
):
    auth_header = create_authorization_header(sample_api_key())
    response = client.post(
        path='/notifications/{}'.format(notification_type),
        data={},
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert response.status_code == 400
    assert json.loads(response.get_data(as_text=True))['message'] == err_msg

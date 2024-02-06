import app
import pytest
import random
import string
from uuid import uuid4
from app.dao import notifications_dao
from app.errors import InvalidRequest
from app.models import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    Notification,
    NotificationHistory,
    SERVICE_PERMISSION_TYPES,
    SMS_TYPE,
    Template,
)
from app.dao.services_dao import dao_update_service
from app.dao.templates_dao import dao_get_all_templates_for_service, dao_update_template
from app.v2.errors import RateLimitError, TooManyRequestsError
from flask import json
from freezegun import freeze_time
from notifications_python_client.authentication import create_jwt_token
from notifications_utils import SMS_CHAR_COUNT_LIMIT
from tests import create_authorization_header


@pytest.mark.parametrize('template_type', [SMS_TYPE, EMAIL_TYPE])
def test_create_notification_should_reject_if_missing_required_fields(
    notify_api, sample_api_key, mocker, template_type
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


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@freeze_time('2016-01-01 11:09:00.061258')
def test_send_notification_with_placeholders_replaced(
    notify_api,
    sample_api_key,
    sample_template,
    mocker,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
            template = sample_template(
                template_type=EMAIL_TYPE, subject='((name))', content='Hello ((name))\nThis is an email from va.gov'
            )
            data = {'to': 'ok@ok.com', 'template': str(template.id), 'personalisation': {'name': 'Jo'}}
            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.post(
                path='/notifications/email',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            response_data = response.get_json()['data']
            notification_id = response_data['notification']['id']
            data.update({'template_version': template.version})

            mocked.assert_called_once()

            result_notification_id, result_queue = mocked.call_args
            result_id, *rest = result_notification_id[0]
            assert result_id == notification_id
            assert result_queue['queue'] == 'send-email-tasks'

            assert response.status_code == 201
            assert response_data['body'] == 'Hello Jo\nThis is an email from va.gov'
            assert response_data['subject'] == 'Jo'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'personalisation, expected_body, expected_subject',
    [
        (
            ('Jo', 'John', 'Josephine'),
            ('Hello \n\n' '* Jo\n' '* John\n' '* Josephine\n' 'This is an email from va.gov'),
            ('Hello 6\n' 'This is an email from va.gov'),
        ),
        pytest.param(None, ('we consider None equivalent to missing personalisation'), '', marks=pytest.mark.xfail),
    ],
)
def test_send_notification_with_placeholders_replaced_with_unusual_types(
    client,
    sample_api_key,
    sample_template,
    mocker,
    personalisation,
    expected_body,
    expected_subject,
):
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    template = sample_template(
        template_type=EMAIL_TYPE, subject='((name))', content='Hello ((name))\nThis is an email from va.gov'
    )
    response = client.post(
        path='/notifications/email',
        data=json.dumps(
            {'to': 'ok@ok.com', 'template': str(template.id), 'personalisation': {'name': personalisation}}
        ),
        headers=[
            ('Content-Type', 'application/json'),
            create_authorization_header(sample_api_key(service=template.service)),
        ],
    )

    assert response.status_code == 201
    response_data = response.get_json()['data']
    assert response_data['body'] == expected_body
    assert response_data['subject'] == expected_subject


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


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('template_type', [SMS_TYPE, EMAIL_TYPE])
def test_should_send_notification_if_restricted_and_a_service_user(
    notify_api,
    sample_api_key,
    sample_template,
    template_type,
    mocker,
    sample_sms_sender_v2,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(template_type))

            template = sample_template(template_type=template_type)
            to = (
                template.service.created_by.mobile_number
                if template_type == SMS_TYPE
                else template.service.created_by.email_address
            )
            template.service.restricted = True
            dao_update_service(template.service)

            data = {'to': to, 'template': template.id}
            sms_sender = sample_sms_sender_v2(service_id=template.service.id)
            if template_type == SMS_TYPE:
                data['sms_sender_id'] = sms_sender.id

            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.post(
                path='/notifications/{}'.format(template_type),
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            mocked.assert_called_once()
            assert response.status_code == 201

            if template_type == SMS_TYPE:
                assert response.get_json()['data']['notification']['sms_sender_id'] == str(sms_sender.id)


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


@freeze_time('2016-01-01 11:09:00.061258')
def test_should_allow_valid_sms_notification(
    notify_api,
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
    sample_sms_sender_v2,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
            template = sample_template()

            data = {
                'to': '6502532222',
                'template': str(template.id),
                'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
            }

            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.post(
                path='/notifications/sms',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert response.status_code == 201
            response_data = response.get_json()['data']
            notification_id = response_data['notification']['id']
            mocked.assert_called_once()
            result_notification_id, result_queue = mocked.call_args
            result_id, *rest = result_notification_id[0]
            assert result_id == notification_id
            assert result_queue['queue'] == 'send-sms-tasks'
            assert notification_id
            assert 'subject' not in response_data
            assert response_data['body'] == template.content
            assert response_data['template_version'] == template.version

    # Teardown
    notification = notify_db_session.session.get(Notification, notification_id)
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


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


@freeze_time('2016-01-01 11:09:00.061258')
def test_should_allow_valid_email_notification(
    notify_api,
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
            template = sample_template(template_type=EMAIL_TYPE)

            data = {'to': 'ok@ok.com', 'template': str(template.id)}

            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.post(
                path='/notifications/email',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 201
            response_data = json.loads(response.get_data(as_text=True))['data']
            notification_id = response_data['notification']['id']

            mocked.assert_called_once()

            result_notification_id, result_queue = mocked.call_args
            result_id, *rest = result_notification_id[0]
            assert result_id == notification_id
            assert result_queue['queue'] == 'send-email-tasks'

            assert response.status_code == 201
            assert notification_id
            assert response_data['subject'] == template.subject
            assert response_data['body'] == template.content
            assert response_data['template_version'] == template.version

    # Teardown
    notification = notify_db_session.session.get(Notification, notification_id)
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


@freeze_time('2016-01-01 12:00:00.061258')
def test_should_block_api_call_if_over_day_limit_for_live_service(
    notify_db_session,
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
            notification = sample_notification(template=email_template, api_key=api_key)

            data = {'to': 'ok@ok.com', 'template': str(email_template.id)}

            auth_header = create_authorization_header(api_key)

            response = client.post(
                path='/notifications/email',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            json.loads(response.get_data(as_text=True))
            assert response.status_code == 429

    # Teardown
    notify_db_session.session.delete(notification)
    notify_db_session.session.commit()


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


@pytest.mark.parametrize('restricted', [True, False])
@freeze_time('2016-01-01 12:00:00.061258')
def test_should_allow_api_call_if_under_day_limit_regardless_of_type(
    notify_api,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
    sample_user,
    mocker,
    restricted,
    sample_sms_sender_v2,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

            service = sample_service(restricted=restricted, message_limit=2, check_if_service_exists=True)
            api_key = sample_api_key(service=service)
            email_template = sample_template(service=service, template_type=EMAIL_TYPE)
            sms_template = sample_template(service=service, template_type=SMS_TYPE)
            sample_notification(template=email_template, api_key=api_key)

            data = {
                'to': sample_user().mobile_number,
                'template': str(sms_template.id),
                'sms_sender_id': str(sample_sms_sender_v2(service_id=service.id).id),
            }

            auth_header = create_authorization_header(api_key)

            response = client.post(
                path='/notifications/sms',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )
            assert response.status_code == 201

    # Teardown
    notification = notify_db_session.session.get(Notification, response.get_json()['data']['notification']['id'])
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


def test_should_not_return_html_in_body(
    notify_api,
    notify_db_session,
    sample_api_key,
    sample_service,
    sample_template,
    mocker,
):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
            email_template = sample_template(service=sample_service(), template_type=EMAIL_TYPE, content='hello\nhi!')

            data = {'to': 'ok@ok.com', 'template': str(email_template.id)}

            auth_header = create_authorization_header(sample_api_key(service=email_template.service))
            response = client.post(
                path='/notifications/email',
                data=json.dumps(data),
                headers=[('Content-Type', 'application/json'), auth_header],
            )

            assert response.status_code == 201
            assert json.loads(response.get_data(as_text=True))['data']['body'] == 'hello\nhi!'

    # Teardown
    notification = notify_db_session.session.get(Notification, response.get_json()['data']['notification']['id'])
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


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
    sample_sms_sender_v2,
):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
        template = sample_template()

        data = {
            'to': '6502532229',
            'template': str(template.id),
            'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
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


def test_should_send_email_if_team_api_key_and_a_service_user(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    mocked_uuid = str(uuid4())
    mocker.patch('app.notifications.process_notifications.uuid.uuid4', return_value=mocked_uuid)
    template = sample_template(template_type=EMAIL_TYPE)

    data = {'to': template.service.created_by.email_address, 'template': template.id}
    auth_header = create_authorization_header(sample_api_key(service=template.service, key_type=KEY_TYPE_TEAM))

    response = client.post(
        path='/notifications/email', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    mocked.assert_called_once()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == mocked_uuid
    assert result_queue['queue'] == 'send-email-tasks'
    assert response.status_code == 201

    # Teardown
    notification = notify_db_session.session.get(Notification, response.get_json()['data']['notification']['id'])
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('restricted', [True, False])
@pytest.mark.parametrize('limit', [0, 1])
def test_should_send_sms_to_anyone_with_test_key(
    client, sample_api_key, sample_template, mocker, restricted, limit, sample_sms_sender_v2
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    mocked_uuid = str(uuid4())
    mocker.patch('app.notifications.process_notifications.uuid.uuid4', return_value=mocked_uuid)

    template = sample_template()
    api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEST)
    data = {
        'to': '6502532222',
        'template': template.id,
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }
    template.service.restricted = restricted
    template.service.message_limit = limit
    auth_header = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))

    response = client.post(
        path='/notifications/sms',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), ('Authorization', 'Bearer {}'.format(auth_header))],
    )

    assert response.status_code == 201
    mocked.assert_called_once()
    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == mocked_uuid
    assert result_queue['queue'] == 'research-mode-tasks'


@pytest.mark.parametrize('restricted', [True, False])
@pytest.mark.parametrize('limit', [0, 1])
def test_should_send_email_to_anyone_with_test_key(
    client, notify_db_session, sample_api_key, sample_template, mocker, restricted, limit
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


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_should_send_sms_if_team_api_key_and_a_service_user(
    client, sample_api_key, sample_template, mocker, sample_sms_sender_v2
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    mocked_uuid = str(uuid4())
    mocker.patch('app.notifications.process_notifications.uuid.uuid4', return_value=mocked_uuid)

    template = sample_template()
    data = {
        'to': template.service.created_by.mobile_number,
        'template': template.id,
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }
    api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEAM)
    auth_header = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))

    response = client.post(
        path='/notifications/sms',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), ('Authorization', 'Bearer {}'.format(auth_header))],
    )

    mocked.assert_called_once()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == mocked_uuid
    assert result_queue['queue'] == 'send-sms-tasks'

    assert response.status_code == 201


@pytest.mark.parametrize('template_type,queue_name', [(SMS_TYPE, 'send-sms-tasks'), (EMAIL_TYPE, 'send-email-tasks')])
def test_should_persist_notification(
    client,
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
    template_type,
    queue_name,
    sample_sms_sender_v2,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(template_type))
    mocked_uuid = str(uuid4())
    mocker.patch('app.notifications.process_notifications.uuid.uuid4', return_value=mocked_uuid)

    template = sample_template(template_type=template_type)
    api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEAM)
    to = (
        template.service.created_by.mobile_number
        if template_type == SMS_TYPE
        else template.service.created_by.email_address
    )
    data = {
        'to': to,
        'template': template.id,
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }

    auth_header = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))

    response = client.post(
        path='/notifications/{}'.format(template_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), ('Authorization', 'Bearer {}'.format(auth_header))],
    )

    assert response.status_code == 201

    mocked.assert_called_once()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == mocked_uuid
    assert result_queue['queue'] == queue_name

    notification = notifications_dao.get_notification_by_id(mocked_uuid)
    assert notification.to == to
    assert notification.template_id == template.id
    assert notification.notification_type == template_type

    # Teardown
    notification = notify_db_session.session.get(Notification, mocked_uuid)
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


@pytest.mark.parametrize('template_type,queue_name', [(SMS_TYPE, 'send-sms-tasks'), (EMAIL_TYPE, 'send-email-tasks')])
def test_should_delete_notification_and_return_error_if_sqs_fails(
    client,
    sample_api_key,
    sample_template,
    mocker,
    template_type,
    queue_name,
    sample_sms_sender_v2,
):
    mocked = mocker.patch(
        'app.celery.provider_tasks.deliver_{}.apply_async'.format(template_type),
        side_effect=Exception('failed to talk to SQS'),
    )
    mocked_uuid = str(uuid4())
    mocker.patch('app.notifications.process_notifications.uuid.uuid4', return_value=mocked_uuid)

    template = sample_template(template_type=template_type)
    api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEAM)
    to = (
        template.service.created_by.mobile_number
        if template_type == SMS_TYPE
        else template.service.created_by.email_address
    )
    data = {
        'to': to,
        'template': template.id,
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }

    auth_header = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))

    with pytest.raises(Exception) as e:
        client.post(
            path='/notifications/{}'.format(template_type),
            data=json.dumps(data),
            headers=[('Content-Type', 'application/json'), ('Authorization', 'Bearer {}'.format(auth_header))],
        )
    assert str(e.value) == 'failed to talk to SQS'

    mocked.assert_called_once()
    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == mocked_uuid
    assert result_queue['queue'] == queue_name

    assert not notifications_dao.get_notification_by_id(mocked_uuid)
    assert not NotificationHistory.query.get(mocked_uuid)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'to_email',
    [
        'simulate-delivered@notifications.va.gov',
        'simulate-delivered-2@notifications.va.gov',
        'simulate-delivered-3@notifications.va.gov',
    ],
)
def test_should_not_persist_notification_or_send_email_if_simulated_email(
    client,
    to_email,
    sample_api_key,
    sample_template,
    mocker,
):
    apply_async = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    template = sample_template(template_type=EMAIL_TYPE)
    data = {'to': to_email, 'template': template.id}

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.post(
        path='/notifications/email', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 201
    apply_async.assert_not_called()
    assert Notification.query.count() == 0


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('to_sms', ['6132532222', '6132532223', '6132532224'])
def test_should_not_persist_notification_or_send_sms_if_simulated_number(
    client,
    to_sms,
    sample_api_key,
    sample_template,
    mocker,
    sample_sms_sender_v2,
):
    apply_async = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    template = sample_template()
    data = {
        'to': to_sms,
        'template': template.id,
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.post(
        path='/notifications/sms', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 201
    apply_async.assert_not_called()
    assert Notification.query.count() == 0


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
    sample_sms_sender_v2,
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
        'sms_sender_id': str(sample_sms_sender_v2(service_id=service.id).id),
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


@pytest.mark.parametrize('service_restricted', [True, False])
@pytest.mark.parametrize('key_type', [KEY_TYPE_NORMAL, KEY_TYPE_TEAM])
@pytest.mark.parametrize(
    'notification_type, to', [(SMS_TYPE, '6502532227'), (EMAIL_TYPE, 'whitelist_recipient@mail.com')]
)
def test_should_send_notification_to_whitelist_recipient(
    client,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    sample_service_whitelist,
    sample_template,
    notification_type,
    to,
    key_type,
    service_restricted,
    mocker,
    sample_sms_sender_v2,
):
    service = sample_service()
    service.message_limit = 2
    service.restricted = service_restricted
    template = sample_template(service=service, template_type=notification_type)
    api_key = sample_api_key(service=service)

    apply_async = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(notification_type))
    if notification_type == SMS_TYPE:
        service_whitelist = sample_service_whitelist(service, phone_number=to)
    elif notification_type == EMAIL_TYPE:
        service_whitelist = sample_service_whitelist(service, email_address=to)

    assert service_whitelist.service_id == service.id
    assert to in [member.recipient for member in service.whitelist]

    sample_notification(template=template, api_key=api_key)

    data = {
        'to': to,
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender_v2(service_id=service.id).id),
    }

    test_key = sample_api_key(service=service, key_type=key_type)
    auth_header = create_jwt_token(secret=test_key.secret, client_id=str(test_key.service_id))

    response = client.post(
        path='/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), ('Authorization', 'Bearer {}'.format(auth_header))],
    )

    assert response.status_code == 201
    json_resp = response.get_json()['data']
    assert json_resp['notification']['id']
    assert json_resp['body'] == template.content
    assert json_resp['template_version'] == template.version
    apply_async.assert_called()

    # Teardown
    notification = notify_db_session.session.get(Notification, json_resp['notification']['id'])
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


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
    sample_sms_sender_v2,
):
    template = sample_template(template_type=template_type)
    data = {
        'to': to,
        'template': template.id,
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
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
    sample_template_with_placeholders,
):
    template = Template.query.get(sample_template_with_placeholders.id)
    from app.notifications.rest import create_template_object_for_notification

    with pytest.raises(InvalidRequest) as e:
        create_template_object_for_notification(template, {})
    assert {'template': ['Missing personalisation:  Name']} == e.value.message


def test_create_template_doesnt_raise_with_too_much_personalisation(sample_template_with_placeholders):
    from app.notifications.rest import create_template_object_for_notification

    template = Template.query.get(sample_template_with_placeholders.id)
    create_template_object_for_notification(template, {'name': 'Jo', 'extra': 'stuff'})


@pytest.mark.parametrize('template_type, should_error', [(SMS_TYPE, True), (EMAIL_TYPE, False)])
def test_create_template_raises_invalid_request_when_content_too_large(
    sample_template,
    template_type,
    should_error,
):
    sample = sample_template(template_type=template_type, content='((long_text))')
    template = Template.query.get(sample.id)
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


@pytest.mark.parametrize('notification_type, send_to', [('sms', '6502532222'), ('email', 'sample@email.com')])
def test_send_notification_uses_priority_queue_when_template_is_marked_as_priority(
    client, notify_db_session, sample_api_key, sample_template, mocker, notification_type, send_to, sample_sms_sender_v2
):
    template = sample_template(template_type=notification_type, process_type='priority')
    mocked = mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(notification_type))

    data = {
        'to': send_to,
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.post(
        path='/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    response_data = json.loads(response.data)['data']
    notification_id = response_data['notification']['id']

    assert response.status_code == 201

    mocked.assert_called_once()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == notification_id
    assert result_queue['queue'] == 'priority-tasks'

    # Teardown
    notification = notify_db_session.session.get(Notification, notification_id)
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


@pytest.mark.parametrize('notification_type, send_to', [('sms', '6502532222'), ('email', 'sample@email.com')])
def test_returns_a_429_limit_exceeded_if_rate_limit_exceeded(
    client,
    sample_api_key,
    sample_template,
    mocker,
    notification_type,
    send_to,
    sample_sms_sender_v2,
):
    template = sample_template(template_type=notification_type)
    persist_mock = mocker.patch('app.notifications.rest.persist_notification')
    deliver_mock = mocker.patch('app.notifications.rest.send_notification_to_queue')

    mocker.patch('app.notifications.rest.check_rate_limiting', side_effect=RateLimitError('LIMIT', 'INTERVAL', 'TYPE'))

    data = {
        'to': send_to,
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }

    auth_header = create_authorization_header(sample_api_key(template.service))

    response = client.post(
        path='/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 429
    persist_mock.assert_not_called()
    deliver_mock.assert_not_called()

    response_json = response.get_json()
    assert response_json['result'] == 'error'
    assert response_json['message'] == 'Exceeded rate limit for key type TYPE of LIMIT requests per INTERVAL seconds'


@pytest.mark.skip(reason="we're not calling check_sms_sender_over_rate_limit here anymore but will move this")
def test_send_sms_returns_a_429_limit_exceeded_if_sms_sender_rate_limit_exceeded(
    client,
    sample_api_key,
    sample_template,
    mocker,
):
    template = sample_template()
    persist_mock = mocker.patch('app.notifications.rest.persist_notification')
    deliver_mock = mocker.patch('app.notifications.rest.send_notification_to_queue')
    sms_sender_mock = mocker.patch('app.dao.service_sms_sender_dao.dao_get_service_sms_sender_by_id')
    sms_sender_mock.rate_limit = mocker.Mock()

    mocker.patch(
        'app.notifications.validators.check_sms_sender_over_rate_limit',
        side_effect=RateLimitError('LIMIT', 'INTERVAL', 'TYPE'),
    )

    data = {'to': '6502532222', 'template': str(template.id)}

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.post(
        path='/notifications/{}'.format('sms'),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    message = json.loads(response.data)['message']
    result = json.loads(response.data)['result']
    assert response.status_code == 429
    assert result == 'error'
    assert message == 'Exceeded rate limit for key type TYPE of LIMIT requests per INTERVAL seconds'

    persist_mock.assert_not_called()
    deliver_mock.assert_not_called()


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_should_allow_store_original_number_on_sms_notification(
    client,
    sample_api_key,
    sample_template,
    mocker,
    sample_sms_sender_v2,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    template = sample_template()
    data = {
        'to': '+16502532222',
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender_v2(service_id=template.service.id).id),
    }

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.post(
        path='/notifications/sms', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    response_data = response.get_json()['data']
    notification_id = response_data['notification']['id']

    mocked.assert_called_once()

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == notification_id
    assert result_queue['queue'] == 'send-sms-tasks'

    assert response.status_code == 201
    assert notification_id
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].to == '+16502532222'


def test_should_not_allow_international_number_on_sms_notification(
    client,
    sample_api_key,
    sample_service,
    sample_template,
    mocker,
    sample_sms_sender_v2,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    service = sample_service(service_permissions=[EMAIL_TYPE, SMS_TYPE])
    assert not service.has_permissions(INTERNATIONAL_SMS_TYPE)
    template = sample_template(service=service)
    assert template.service.id == service.id

    data = {
        'to': '+20-12-1234-1234',
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender_v2(service_id=service.id).id),
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


def test_should_allow_international_number_on_sms_notification(
    client,
    notify_db_session,
    sample_api_key,
    sample_inbound_number,
    sample_service,
    sample_template,
    mocker,
    sample_sms_sender_v2,
):
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    service = sample_service(service_permissions=SERVICE_PERMISSION_TYPES)
    sample_inbound_number(service_id=service.id)
    template = sample_template(service=service)

    data = {
        'to': '+20-12-1234-1234',
        'template': str(template.id),
        'sms_sender_id': str(sample_sms_sender_v2(service_id=service.id).id),
    }

    auth_header = create_authorization_header(sample_api_key(service=service))

    response = client.post(
        path='/notifications/sms', data=json.dumps(data), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 201

    # Teardown
    notification = notify_db_session.session.get(Notification, response.get_json()['data']['notification']['id'])
    if notification:
        notify_db_session.session.delete(notification)
        notify_db_session.session.commit()


def test_should_not_allow_sms_notifications_if_service_permission_not_set(
    client,
    mocker,
    sample_api_key,
    sample_template_without_sms_permission,
    sample_sms_sender_v2,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    service = sample_template_without_sms_permission.service
    data = {
        'to': '+16502532222',
        'template': str(sample_template_without_sms_permission.id),
        'sms_sender_id': str(sample_sms_sender_v2(service_id=service.id).id),
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
    sample_template_without_email_permission,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    data = {'to': 'notify@digital.cabinet-office.gov.uk', 'template': str(sample_template_without_email_permission.id)}

    auth_header = create_authorization_header(sample_api_key(service=sample_template_without_email_permission.service))

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


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('notification_type, recipient', [('sms', '6502532222'), ('email', 'test@va.gov')])
def test_post_notification_should_set_reply_to_text(
    client,
    sample_api_key,
    sample_service_email_reply_to,
    sample_service,
    sample_template,
    mocker,
    notification_type,
    recipient,
    sample_sms_sender_v2,
):
    service = sample_service()
    mocker.patch('app.celery.provider_tasks.deliver_{}.apply_async'.format(notification_type))
    template = sample_template(service=service, template_type=notification_type)
    expected_reply_to = sample_sms_sender_v2(service_id=service.id).sms_sender

    if notification_type == EMAIL_TYPE:
        expected_reply_to = 'reply_to@va.gov'
        sample_service_email_reply_to(service, email_address=expected_reply_to, is_default=True)

    data = {
        'to': recipient,
        'template': str(template.id),
        'sms_sender_id': str(expected_reply_to),
    }

    response = client.post(
        '/notifications/{}'.format(notification_type),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), create_authorization_header(sample_api_key(service=service))],
    )

    assert response.status_code == 201
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == expected_reply_to

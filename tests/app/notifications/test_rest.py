"""
This module tests GET requests to /notifications endpoints.
"""

import pytest
import uuid
from app.dao.notifications_dao import dao_update_notification
from app.dao.templates_dao import dao_update_template
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    SMS_TYPE,
)
from flask import current_app
from freezegun import freeze_time
from tests import create_authorization_header


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_get_notification_by_id(
    client,
    sample_notification,
    notification_type,
    sample_sms_sender,
    sample_api_key,
):
    notification_to_get = sample_notification(gen_type=notification_type)

    api_key = sample_api_key(service=notification_to_get.service)
    auth_header = create_authorization_header(api_key)
    response = client.get(f'/notifications/{notification_to_get.id}', headers=[auth_header])

    assert response.status_code == 200
    notification = response.get_json()['data']['notification']
    assert notification['status'] == 'created'
    assert notification['template'] == {
        'id': str(notification_to_get.template.id),
        'name': notification_to_get.template.name,
        'template_type': notification_to_get.template.template_type,
        'version': 1,
    }
    assert notification['to'] == notification_to_get.to
    assert notification['service'] == str(notification_to_get.service_id)
    assert notification['body'] == notification_to_get.template.content
    assert notification.get('subject', None) == notification_to_get.subject

    if notification_type == SMS_TYPE:
        sms_sender_id = notification_to_get.service.get_default_sms_sender_id()
        assert notification['sms_sender_id'] == sms_sender_id


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('notification_id', ['1234-badly-formatted-id-7890', '0'])
@pytest.mark.parametrize('notification_type', (EMAIL_TYPE, SMS_TYPE))
def test_get_notification_by_invalid_id(
    client,
    sample_api_key,
    sample_notification,
    sample_email_notification,
    sample_letter_notification,
    notification_id,
    notification_type,
):
    if notification_type == EMAIL_TYPE:
        notification_to_get = sample_email_notification
    elif notification_type == SMS_TYPE:
        notification_to_get = sample_notification
    elif notification_type == LETTER_TYPE:
        notification_to_get = sample_letter_notification

    auth_header = create_authorization_header(sample_api_key(service=notification_to_get.service))

    response = client.get('/notifications/{}'.format(notification_id), headers=[auth_header])

    assert response.status_code == 405


def test_get_notification_empty_result(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    response = client.get(path='/notifications/{}'.format(uuid.uuid4()), headers=[auth_header])

    assert response.status_code == 404
    response_json = response.get_json()
    assert response_json['result'] == 'error'
    assert response_json['message'] == 'No result found'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'api_key_type, notification_key_type',
    [
        (KEY_TYPE_NORMAL, KEY_TYPE_TEAM),
        (KEY_TYPE_NORMAL, KEY_TYPE_TEST),
        (KEY_TYPE_TEST, KEY_TYPE_NORMAL),
        (KEY_TYPE_TEST, KEY_TYPE_TEAM),
        (KEY_TYPE_TEAM, KEY_TYPE_NORMAL),
        (KEY_TYPE_TEAM, KEY_TYPE_TEST),
    ],
)
def test_get_notification_from_different_api_key_works(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
    api_key_type,
    notification_key_type,
):
    api_key_0 = sample_api_key(key_type=api_key_type)
    api_key_1 = sample_api_key(service=api_key_0.service)
    template = sample_template(template_type=EMAIL_TYPE)
    notification = sample_notification(template=template, api_key=api_key_0)
    sample_notification.key_type = notification_key_type

    response = client.get(
        path='/notifications/{}'.format(sample_notification.id), headers=create_authorization_header(api_key_1)
    )

    assert response.status_code == 200
    response_json = response.get_json()['data']['notification']
    assert response_json['notification_type'] == SMS_TYPE, 'This is the default for the sample_notification fixture.'
    assert response_json['sms_sender_id'] == str(notification.sms_sender_id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('key_type', [KEY_TYPE_NORMAL, KEY_TYPE_TEAM, KEY_TYPE_TEST])
def test_get_notification_from_different_api_key_of_same_type_succeeds(
    client, sample_api_key, sample_notification, key_type, sample_sms_sender
):
    notification = sample_notification()

    creation_api_key = sample_api_key(
        service=notification.service,
        key_type=key_type,
    )

    querying_api_key = sample_api_key(
        service=notification.service,
        key_type=key_type,
    )

    notification.api_key = creation_api_key
    notification.key_type = key_type
    dao_update_notification(notification)
    assert notification.api_key_id != querying_api_key.id

    response = client.get(
        path=f'/notifications/{notification.id}', headers=create_authorization_header(querying_api_key)
    )

    assert response.status_code == 200
    response_json = response.get_json()['data']['notification']
    assert response_json['id'] == str(notification.id)
    assert response_json['sms_sender_id'] == str(sample_sms_sender.id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_all_notifications(
    client,
    sample_api_key,
    sample_notification,
    sample_sms_sender_v2,
):
    notification = sample_notification()
    auth_header = create_authorization_header(sample_api_key(service=notification.service))

    response = client.get('/notifications', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['notifications'][0]
    assert response_json['status'] == 'created'
    assert response_json['template'] == {
        'id': str(notification.template.id),
        'name': notification.template.name,
        'template_type': notification.template.template_type,
        'version': 1,
    }

    assert response_json['to'] == '+16502532222'
    assert response_json['service'] == str(notification.service_id)
    assert response_json['body'] == notification.content
    assert response_json['sms_sender_id'] == str(sample_sms_sender_v2().id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_normal_api_key_returns_notifications_created_from_jobs_and_from_api(
    client,
    sample_template,
    sample_api_key,
    sample_notification,
    sample_sms_sender,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)

    sample_notification(template=template, api_key=api_key, sms_sender_id=sample_sms_sender.id)

    response = client.get(path='/notifications', headers=create_authorization_header(api_key))

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 2
    assert all(x['sms_sender_id'] == str(sample_sms_sender.id) for x in response_json)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('key_type', [KEY_TYPE_NORMAL, KEY_TYPE_TEAM, KEY_TYPE_TEST])
def test_get_all_notifications_only_returns_notifications_of_matching_type(
    client,
    sample_template,
    sample_api_key,
    sample_notification,
    key_type,
    sample_sms_sender,
):
    template = sample_template()
    normal_notification = sample_notification(
        template=template,
        api_key=sample_api_key(key_type=KEY_TYPE_NORMAL),
        key_type=KEY_TYPE_NORMAL,
        sms_sender_id=sample_sms_sender.id,
    )

    team_notification = sample_notification(
        template=template,
        api_key=sample_api_key(key_type=KEY_TYPE_TEAM),
        key_type=KEY_TYPE_TEAM,
        sms_sender_id=sample_sms_sender.id,
    )

    test_notification = sample_notification(
        template=template,
        api_key=sample_api_key(key_type=KEY_TYPE_TEST),
        key_type=KEY_TYPE_TEST,
        sms_sender_id=sample_sms_sender.id,
    )

    notification_objs = {
        KEY_TYPE_NORMAL: normal_notification,
        KEY_TYPE_TEAM: team_notification,
        KEY_TYPE_TEST: test_notification,
    }

    response = client.get(
        path='/notifications', headers=create_authorization_header(notification_objs[key_type].api_key)
    )

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 1
    assert response_json[0]['id'] == str(notification_objs[key_type].id)
    assert all(x['sms_sender_id'] == str(sample_sms_sender.id) for x in response_json)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('key_type', [KEY_TYPE_NORMAL, KEY_TYPE_TEAM, KEY_TYPE_TEST])
def test_do_not_return_job_notifications_by_default(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
    key_type,
    sample_sms_sender_v2,
):
    template = sample_template()
    sms_sender = sample_sms_sender_v2()
    team_api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEAM)
    normal_api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_NORMAL)
    test_api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEST)

    sample_notification(template=template, sms_sender_id=sms_sender.id)

    normal_notification = sample_notification(template=template, api_key=normal_api_key, sms_sender_id=sms_sender.id)

    team_notification = sample_notification(template=template, api_key=team_api_key, sms_sender_id=sms_sender.id)

    test_notification = sample_notification(template=template, api_key=test_api_key, sms_sender_id=sms_sender.id)

    notification_objs = {
        KEY_TYPE_NORMAL: normal_notification,
        KEY_TYPE_TEAM: team_notification,
        KEY_TYPE_TEST: test_notification,
    }

    response = client.get(
        path='/notifications', headers=create_authorization_header(notification_objs[key_type].api_key)
    )

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 1
    assert response_json[0]['id'] == str(notification_objs[key_type].id)
    assert all(x['sms_sender_id'] == str(sms_sender.id) for x in response_json)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize('key_type', [(KEY_TYPE_NORMAL, 2), (KEY_TYPE_TEAM, 1), (KEY_TYPE_TEST, 1)])
def test_only_normal_api_keys_can_return_job_notifications(
    client,
    sample_notification_with_job,
    sample_template,
    sample_api_key,
    sample_team_api_key,
    sample_test_api_key,
    key_type,
    sample_sms_sender,
    sample_notification,
):
    template = sample_template()
    normal_notification = sample_notification(
        template=template,
        api_key=sample_api_key(key_type=KEY_TYPE_NORMAL),
        key_type=KEY_TYPE_NORMAL,
        sms_sender_id=sample_sms_sender.id,
    )

    team_notification = sample_notification(
        template=template,
        api_key=sample_api_key(key_type=KEY_TYPE_TEAM),
        key_type=KEY_TYPE_TEAM,
        sms_sender_id=sample_sms_sender.id,
    )

    test_notification = sample_notification(
        template=template,
        api_key=sample_api_key(key_type=KEY_TYPE_TEST),
        key_type=KEY_TYPE_TEST,
        sms_sender_id=sample_sms_sender.id,
    )

    notification_objs = {
        KEY_TYPE_NORMAL: normal_notification,
        KEY_TYPE_TEAM: team_notification,
        KEY_TYPE_TEST: test_notification,
    }

    response = client.get(
        path='/notifications?include_jobs=true',
        headers=create_authorization_header(notification_objs[key_type[0]].api_key),
    )

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == key_type[1]
    assert response_json[0]['id'] == str(notification_objs[key_type[0]].id)
    assert all(x['sms_sender_id'] == str(sample_sms_sender.id) for x in response_json)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_all_notifications_newest_first(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    notification_1 = sample_notification(template=template)
    notification_2 = sample_notification(template=template)
    notification_3 = sample_notification(template=template)

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.get('/notifications', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 3
    assert response_json[0]['to'] == notification_3.to
    assert response_json[1]['to'] == notification_2.to
    assert response_json[2]['to'] == notification_1.to


def test_should_reject_invalid_page_param(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    response = client.get('/notifications?page=invalid', headers=[auth_header])

    assert response.status_code == 400
    response_json = response.get_json()
    assert response_json['result'] == 'error'
    assert 'Not a valid integer.' in response_json['message']['page']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_valid_page_size_param(
    notify_api,
    sample_api_key,
    sample_template,
    sample_notification,
):
    with notify_api.test_request_context():
        template = sample_template(template_type=EMAIL_TYPE)
        sample_notification(template)
        sample_notification(template)
        with notify_api.test_client() as client:
            auth_header = create_authorization_header(sample_api_key(service=template.service))

            response = client.get('/notifications?page=1&page_size=1', headers=[auth_header])

            assert response.status_code == 200
            response_json = response.get_json()
            assert len(response_json['notifications']) == 1
            assert response_json['total'] == 2
            assert response_json['page_size'] == 1


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_invalid_page_size_param(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(template)
    sample_notification(template)

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.get('/notifications?page=1&page_size=invalid', headers=[auth_header])

    assert response.status_code == 400
    response_json = response.get_json()
    assert response_json['result'] == 'error'
    assert 'Not a valid integer.' in response_json['message']['page_size']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_should_return_pagination_links(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    # Effectively mocking page size
    original_page_size = current_app.config['API_PAGE_SIZE']
    try:
        current_app.config['API_PAGE_SIZE'] = 1
        template = sample_template(template_type=EMAIL_TYPE)

        sample_notification(template)
        notification_2 = sample_notification(template)
        sample_notification(template)

        auth_header = create_authorization_header(sample_api_key(service=template.service))

        response = client.get('/notifications?page=2', headers=[auth_header])

        assert response.status_code == 200
        response_json = response.get_json()
        assert len(response_json['notifications']) == 1
        assert response_json['links']['last'] == '/notifications?page=3'
        assert response_json['links']['prev'] == '/notifications?page=1'
        assert response_json['links']['next'] == '/notifications?page=3'
        assert response_json['notifications'][0]['to'] == notification_2.to

    finally:
        current_app.config['API_PAGE_SIZE'] = original_page_size


def test_get_all_notifications_returns_empty_list(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    response = client.get('/notifications', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()
    assert len(response_json['notifications']) == 0


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_filter_by_template_type(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    email_template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(sample_template(service=email_template.service))
    sample_notification(email_template)

    auth_header = create_authorization_header(sample_api_key(service=email_template.service))

    response = client.get('/notifications?template_type=sms', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 1
    assert response_json[0]['template']['template_type'] == SMS_TYPE


def test_filter_by_multiple_template_types(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    email_template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(template=sample_template(service=email_template.service))
    sample_notification(template=email_template)

    auth_header = create_authorization_header(sample_api_key(service=email_template.service))

    response = client.get('/notifications?template_type=sms&template_type=email', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 2
    assert {SMS_TYPE, EMAIL_TYPE} == set(x['template']['template_type'] for x in response_json)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_filter_by_status(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(template, status='delivered')
    sample_notification(template)

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.get('/notifications?status=delivered', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 1
    assert response_json[0]['status'] == 'delivered'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_filter_by_multiple_statuses(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(template, status='delivered')
    sample_notification(template, status='sending')

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.get('/notifications?status=delivered&status=sending', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 2
    assert {'delivered', 'sending'} == set(x['status'] for x in response_json)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_filter_by_status_and_template_type(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    email_template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(sample_template())
    sample_notification(email_template)
    sample_notification(email_template, status='delivered')

    auth_header = create_authorization_header(sample_api_key(email_template.service))

    response = client.get('/notifications?template_type=email&status=delivered', headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['notifications']
    assert len(response_json) == 1
    assert response_json[0]['template']['template_type'] == EMAIL_TYPE
    assert response_json[0]['status'] == 'delivered'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_notification_by_id_returns_merged_template_content(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
    sample_sms_sender_v2,
):
    sms_sender = sample_sms_sender_v2()
    template = sample_template(content='Hello (( Name))\nYour thing is due soon')

    notification = sample_notification(
        template=template, personalisation={'name': 'world'}, sms_sender_id=sms_sender.id
    )
    assert notification.notification_type == SMS_TYPE, 'This is the default.'

    auth_header = create_authorization_header(sample_api_key(notification.service))

    response = client.get('/notifications/{}'.format(notification.id), headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['data']['notification']
    assert response_json['body'] == 'Hello world\nYour thing is due soon'
    assert 'subject' not in response_json
    assert response_json['content_char_count'] == 34
    assert response_json['sms_sender_id'] == str(sms_sender.id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_notification_by_id_returns_merged_template_content_for_email(
    client,
    sample_api_key,
    sample_email_template_with_placeholders,
    sample_notification,
):
    notification = sample_notification(sample_email_template_with_placeholders, personalisation={'name': 'world'})
    auth_header = create_authorization_header(sample_api_key(service=notification.service))

    response = client.get('/notifications/{}'.format(notification.id), headers=[auth_header])

    assert response.status_code == 200
    response_json = response.get_json()['data']['notification']
    assert response_json['body'] == 'Hello world\nThis is an email from GOV.UK'
    assert response_json['subject'] == 'world'
    assert response_json['content_char_count'] is None


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_notifications_for_service_returns_merged_template_content(
    client,
    sample_api_key,
    sample_template_with_placeholders,
    sample_notification,
):
    with freeze_time('2001-01-01T12:00:00'):
        sample_notification(sample_template_with_placeholders, personalisation={'name': 'merged with first'})

    with freeze_time('2001-01-01T12:00:01'):
        sample_notification(sample_template_with_placeholders, personalisation={'name': 'merged with second'})

    auth_header = create_authorization_header(sample_api_key(service=sample_template_with_placeholders.service))

    response = client.get(path='/notifications', headers=[auth_header])

    assert response.status_code == 200
    assert {noti['body'] for noti in response.get_json()['notifications']} == {
        'Hello merged with first\nYour thing is due soon',
        'Hello merged with second\nYour thing is due soon',
    }


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_notification_selects_correct_template_for_personalisation(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    template = sample_template()
    sample_notification(template=template)
    original_content = template.content
    template.content = '((name))'
    dao_update_template(template)

    sample_notification(template=template, personalisation={'name': 'foo'})

    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.get(path='/notifications', headers=[auth_header])
    assert response.status_code == 200

    resp = response.get_json()
    notis = sorted(resp['notifications'], key=lambda x: x['template_version'])
    assert len(notis) == 2
    assert notis[0]['template_version'] == 1
    assert notis[0]['body'] == original_content
    assert notis[1]['template_version'] == 2
    assert notis[1]['body'] == 'foo'

    assert notis[0]['template_version'] == notis[0]['template']['version']
    assert notis[1]['template_version'] == notis[1]['template']['version']

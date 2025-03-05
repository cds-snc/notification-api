import base64
import botocore
import json
import pytest
import random
import requests_mock
import string
import uuid

from datetime import datetime, timedelta, date
from flask import url_for
from flask_jwt_extended import create_access_token
from freezegun import freeze_time
from notifications_utils import SMS_CHAR_COUNT_LIMIT
from notifications_utils.template import HTMLEmailTemplate
from pypdf.errors import PdfReadError
from sqlalchemy import select

from app.constants import EDIT_TEMPLATES, EMAIL_TYPE, LETTER_TYPE, SERVICE_PERMISSION_TYPES, SES_PROVIDER, SMS_TYPE
from app.dao.permissions_dao import permission_dao
from app.dao.templates_dao import dao_get_template_by_id, dao_redact_template
from app.feature_flags import FeatureFlag
from app.models import (
    Template,
    TemplateHistory,
    TemplateRedacted,
    ProviderDetails,
    Permission,
)
from tests import create_admin_authorization_header
from tests.app.conftest import service_cleanup
from tests.app.db import (
    create_letter_contact,
    create_template_folder,
)
from tests.app.factories.feature_flag import mock_feature_flag
from tests.conftest import set_config_values


@pytest.mark.skip(reason='TODO #2336 - Fail due to orphaned User object')
@pytest.mark.parametrize(
    'template_type, subject',
    [
        (SMS_TYPE, None),
        (EMAIL_TYPE, 'subject'),
    ],
)
def test_should_create_a_new_template_for_a_service(
    notify_db_session,
    client,
    sample_service,
    sample_user,
    template_type,
    subject,
):
    user = sample_user()
    service = sample_service(service_permissions=[template_type])
    data = {
        'name': 'my template',
        'template_type': template_type,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(user.id),
    }
    if subject:
        data.update({'subject': subject})
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        '/service/{}/template'.format(service.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data,
    )
    assert response.status_code == 201
    json_resp = response.get_json()
    assert json_resp['data']['name'] == 'my template'
    assert json_resp['data']['template_type'] == template_type
    assert json_resp['data']['content'] == 'template <b>content</b>'
    assert json_resp['data']['service'] == str(service.id)
    assert json_resp['data']['id']
    assert json_resp['data']['version'] == 1
    assert json_resp['data']['process_type'] == 'normal'
    assert json_resp['data']['created_by'] == str(user.id)
    if subject:
        assert json_resp['data']['subject'] == 'subject'
    else:
        assert not json_resp['data']['subject']

    if template_type == LETTER_TYPE:
        assert json_resp['data']['postage'] == 'first'
    else:
        assert not json_resp['data']['postage']

    template = notify_db_session.session.get(Template, json_resp['data']['id'])
    from app.schemas import template_schema

    assert sorted(json_resp['data']) == sorted(template_schema.dump(template))


@pytest.mark.skip(reason='TODO #2336 - Fail due to orphaned User object')
def test_should_create_a_new_template_with_a_valid_provider(
    notify_db_session,
    client,
    sample_service,
    sample_user,
    sample_provider,
):
    user = sample_user()
    provider = sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    service = sample_service(service_permissions=[EMAIL_TYPE])
    data = {
        'name': 'my template',
        'template_type': EMAIL_TYPE,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(user.id),
        'provider_id': str(provider.id),
        'subject': 'subject',
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        f'/service/{service.id}/template', headers=[('Content-Type', 'application/json'), auth_header], data=data
    )
    assert response.status_code == 201
    json_resp = response.get_json()
    assert json_resp['data']['provider_id'] == str(provider.id)

    template = notify_db_session.session.get(Template, json_resp['data']['id'])
    assert template.provider_id == provider.id

    service_cleanup([service.id], notify_db_session.session)


@pytest.mark.parametrize('template_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_create_template_with_non_existent_provider(
    client, sample_service, sample_user, fake_uuid, template_type
):
    user = sample_user()
    service = sample_service(user=user, service_permissions=[template_type])
    data = {
        'name': 'my template',
        'template_type': template_type,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(user.id),
        'provider_id': str(fake_uuid),
        'subject': 'subject',
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            f'/service/{service.id}/template', headers=[('Content-Type', 'application/json'), auth_header], data=data
        )
    assert response.status_code == 400

    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == f'invalid {template_type}_provider_id'


@pytest.mark.parametrize('template_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_create_template_with_inactive_provider(
    client, sample_service, sample_user, fake_uuid, template_type, mocker
):
    user = sample_user()
    service = sample_service(user=user, service_permissions=[template_type])
    data = {
        'name': 'my template',
        'template_type': template_type,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(user.id),
        'provider_id': str(fake_uuid),
        'subject': 'subject',
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = False
    mocked_provider_details.notification_type = template_type
    mocked_provider_details.id = fake_uuid
    mocker.patch(
        'app.template.rest.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details
    )

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            f'/service/{service.id}/template', headers=[('Content-Type', 'application/json'), auth_header], data=data
        )
    assert response.status_code == 400

    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == f'invalid {template_type}_provider_id'


@pytest.mark.parametrize('template_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_create_template_with_incorrect_provider_type(
    client, sample_service, sample_user, fake_uuid, template_type, mocker
):
    user = sample_user()
    service = sample_service(user=user, service_permissions=[template_type])
    data = {
        'name': 'my template',
        'template_type': template_type,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(user.id),
        'provider_id': str(fake_uuid),
        'subject': 'subject',
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = True
    mocked_provider_details.notification_type = LETTER_TYPE
    mocked_provider_details.id = fake_uuid
    mocker.patch(
        'app.template.rest.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details
    )

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            f'/service/{service.id}/template', headers=[('Content-Type', 'application/json'), auth_header], data=data
        )
    assert response.status_code == 400

    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == f'invalid {template_type}_provider_id'


@pytest.mark.skip(reason='TODO #2336 - Fail due to orphaned User object')
def test_create_a_new_template_for_a_service_adds_folder_relationship(notify_db_session, client, sample_service):
    service = sample_service()
    parent_folder = create_template_folder(service=service, name='parent folder')
    template_name = str(uuid.uuid4())
    data = {
        'name': template_name,
        'template_type': SMS_TYPE,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(service.users[0].id),
        'parent_folder_id': str(parent_folder.id),
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        '/service/{}/template'.format(service.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data,
    )
    assert response.status_code == 201

    stmt = select(Template).where(Template.name == template_name)
    template = notify_db_session.session.scalars(stmt).first()

    assert template.folder == parent_folder


def test_create_template_should_return_400_if_folder_is_for_a_different_service(client, sample_service):
    service = sample_service()
    service2 = sample_service()
    parent_folder = create_template_folder(service=service2)

    data = {
        'name': 'my template',
        'template_type': SMS_TYPE,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(service.users[0].id),
        'parent_folder_id': str(parent_folder.id),
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            '/service/{}/template'.format(service.id),
            headers=[('Content-Type', 'application/json'), auth_header],
            data=data,
        )
    assert response.status_code == 400
    assert response.get_json()['message'] == 'parent_folder_id not found'


def test_create_template_should_return_400_if_folder_does_not_exist(client, sample_service):
    service = sample_service()
    data = {
        'name': 'my template',
        'template_type': SMS_TYPE,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': str(service.users[0].id),
        'parent_folder_id': str(uuid.uuid4()),
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            '/service/{}/template'.format(service.id),
            headers=[('Content-Type', 'application/json'), auth_header],
            data=data,
        )
    assert response.status_code == 400
    assert response.get_json()['message'] == 'parent_folder_id not found'


def test_should_raise_error_if_service_does_not_exist_on_create(client, sample_user, fake_uuid):
    data = {
        'name': 'my template',
        'template_type': SMS_TYPE,
        'content': 'template content',
        'service': fake_uuid,
        'created_by': str(sample_user().id),
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        '/service/{}/template'.format(fake_uuid), headers=[('Content-Type', 'application/json'), auth_header], data=data
    )
    json_resp = response.get_json()
    assert response.status_code == 404
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'No result found'


@pytest.mark.parametrize(
    'permissions, template_type, subject, expected_error',
    [
        ([EMAIL_TYPE], SMS_TYPE, None, {'template_type': ['Creating text message templates is not allowed']}),
        ([SMS_TYPE], EMAIL_TYPE, 'subject', {'template_type': ['Creating email templates is not allowed']}),
        ([SMS_TYPE], LETTER_TYPE, 'subject', {'template_type': ['Creating letter templates is not allowed']}),
    ],
)
def test_should_raise_error_on_create_if_no_permission(
    client, sample_service, sample_user, permissions, template_type, subject, expected_error
):
    service = sample_service(service_permissions=permissions)
    data = {
        'name': 'my template',
        'template_type': template_type,
        'content': 'template content',
        'service': str(service.id),
        'created_by': str(sample_user().id),
    }
    if subject:
        data.update({'subject': subject})

    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            '/service/{}/template'.format(service.id),
            headers=[('Content-Type', 'application/json'), auth_header],
            data=data,
        )
    json_resp = response.get_json()
    assert response.status_code == 403
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == expected_error


@pytest.mark.parametrize(
    'template_type, permissions, expected_error',
    [
        (SMS_TYPE, [EMAIL_TYPE], {'template_type': ['Updating text message templates is not allowed']}),
        (EMAIL_TYPE, [LETTER_TYPE], {'template_type': ['Updating email templates is not allowed']}),
        # (LETTER_TYPE, [SMS_TYPE], {'template_type': ['Updating letter templates is not allowed']})
    ],
)
def test_should_be_error_on_update_if_no_permission(
    client,
    template_type,
    permissions,
    expected_error,
    sample_service,
    sample_template,
    sample_user,
):
    user = sample_user()
    service = sample_service(user=user, service_permissions=permissions)
    template = sample_template(service=service, template_type=template_type)

    data = {'content': 'new template content', 'created_by': str(user.id)}

    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    update_response = client.post(
        '/service/{}/template/{}'.format(service.id, template.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data,
    )

    json_resp = json.loads(update_response.get_data(as_text=True))
    assert update_response.status_code == 403
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == expected_error


@pytest.mark.skip(reason='TODO #2336 - Fail due to orphaned User object')
def test_should_error_if_created_by_missing(client, sample_service):
    service_id = str(sample_service().id)
    data = {'name': 'my template', 'template_type': SMS_TYPE, 'content': 'template content', 'service': service_id}
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        '/service/{}/template'.format(service_id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data,
    )
    json_resp = response.get_json()
    assert response.status_code == 400
    assert json_resp['errors'][0]['error'] == 'ValidationError'
    assert json_resp['errors'][0]['message'] == 'created_by is a required property'


def test_should_be_error_if_service_does_not_exist_on_update(client, fake_uuid):
    data = {'name': 'my template'}
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        '/service/{}/template/{}'.format(fake_uuid, fake_uuid),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data,
    )
    json_resp = response.get_json()
    assert response.status_code == 404
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'No result found'


@pytest.mark.parametrize('template_type', [EMAIL_TYPE, LETTER_TYPE])
def test_must_have_a_subject_on_an_email_or_letter_template(client, sample_user, sample_service, template_type):
    service = sample_service()
    data = {
        'name': 'my template',
        'template_type': template_type,
        'content': 'template content',
        'service': str(service.id),
        'created_by': str(sample_user().id),
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            '/service/{}/template'.format(service.id),
            headers=[('Content-Type', 'application/json'), auth_header],
            data=data,
        )
    json_resp = response.get_json()
    assert json_resp['errors'][0]['error'] == 'ValidationError'
    assert json_resp['errors'][0]['message'] == 'subject is a required property'


def test_update_should_update_a_template(client, sample_user, sample_service, sample_template):
    service = sample_service(service_permissions=[SMS_TYPE])
    template = sample_template(service=service, template_type=SMS_TYPE)

    new_content = 'My template has new content.'
    data = json.dumps(
        {
            'content': new_content,
            'created_by': str(sample_user().id),
        }
    )

    auth_header = create_admin_authorization_header()

    update_response = client.post(
        '/service/{}/template/{}'.format(service.id, template.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data,
    )

    assert update_response.status_code == 200
    update_json_resp = update_response.get_json()
    assert update_json_resp['data']['content'] == new_content
    assert update_json_resp['data']['name'] == template.name
    assert update_json_resp['data']['template_type'] == template.template_type
    assert update_json_resp['data']['version'] == 2


def test_should_be_able_to_archive_template(notify_db_session, client, sample_template):
    template_name = f'template {str(uuid.uuid4())}'
    template = sample_template(name=template_name)
    data = {
        'name': template.name,
        'template_type': template.template_type,
        'content': template.content,
        'archived': True,
        'service': str(template.service.id),
        'created_by': str(template.created_by.id),
    }

    json_data = json.dumps(data)

    auth_header = create_admin_authorization_header()

    resp = client.post(
        '/service/{}/template/{}'.format(template.service.id, template.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=json_data,
    )

    assert resp.status_code == 200
    stmt = select(Template).where(Template.name == template.name)
    assert notify_db_session.session.scalars(stmt).one().archived


def test_get_precompiled_template_for_service_when_service_has_existing_precompiled_template(
    client, sample_service, sample_template
):
    service = sample_service()
    template = sample_template(
        service=service,
        name=f'Exisiting precompiled template {str(uuid.uuid4())}',
        template_type=LETTER_TYPE,
        hidden=True,
    )
    assert len(service.templates) == 1

    response = client.get(
        '/service/{}/template/precompiled'.format(service.id),
        headers=[create_admin_authorization_header()],
    )

    assert response.status_code == 200
    assert len(service.templates) == 1

    data = response.get_json()
    assert data['name'] == template.name
    assert data['hidden'] is True


@pytest.mark.skip(reason='TODO #2336 - Fail due to orphaned User object')
def test_should_be_able_to_get_all_templates_for_a_service(client, sample_user, sample_service):
    user = sample_user()
    service = sample_service()
    template_name_1 = str(uuid.uuid4())
    template_name_2 = str(uuid.uuid4())

    data = {
        'name': template_name_1,
        'template_type': EMAIL_TYPE,
        'subject': 'subject 1',
        'content': 'template content',
        'service': str(service.id),
        'created_by': str(user.id),
    }

    data_1 = json.dumps(data)
    data = {
        'name': template_name_2,
        'template_type': EMAIL_TYPE,
        'subject': 'subject 2',
        'content': 'template content',
        'service': str(service.id),
        'created_by': str(user.id),
    }
    data_2 = json.dumps(data)
    auth_header = create_admin_authorization_header()
    client.post(
        '/service/{}/template'.format(service.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data_1,
    )
    auth_header = create_admin_authorization_header()

    client.post(
        '/service/{}/template'.format(service.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=data_2,
    )

    auth_header = create_admin_authorization_header()

    response = client.get('/service/{}/template'.format(service.id), headers=[auth_header])

    assert response.status_code == 200

    update_json_resp = response.get_json()
    data_dict = {item['name']: item for item in update_json_resp['data']}

    assert data_dict[template_name_1]['name'] == template_name_1
    assert data_dict[template_name_1]['version'] == 1
    assert data_dict[template_name_1]['created_at']
    assert data_dict[template_name_2]['name'] == template_name_2
    assert data_dict[template_name_2]['version'] == 1
    assert data_dict[template_name_2]['created_at']


def test_should_get_only_templates_for_that_service(admin_request, sample_service, sample_template):
    service_grp_0 = sample_service()
    service_grp_1 = sample_service()
    templates = [
        sample_template(service=service_grp_0),
        sample_template(service=service_grp_0),
        sample_template(service=service_grp_1, template_type=EMAIL_TYPE),
    ]
    ids = [str(t.id) for t in templates]

    json_resp_0 = admin_request.get('template.get_all_templates_for_service', service_id=service_grp_0.id)
    json_resp_1 = admin_request.get('template.get_all_templates_for_service', service_id=service_grp_1.id)

    assert {template['id'] for template in json_resp_0['data']} == {ids[0], ids[1]}
    assert {template['id'] for template in json_resp_1['data']} == {ids[2]}


@pytest.mark.parametrize('template_type', [EMAIL_TYPE, SMS_TYPE])
def test_should_get_a_single_template(
    client,
    template_type,
    sample_template,
):
    template = sample_template(template_type=template_type)
    response = client.get(
        f'/service/{template.service_id}/template/{template.id}', headers=[create_admin_authorization_header()]
    )

    data = response.get_json()['data']

    assert response.status_code == 200
    assert data['content'] == template.content
    assert data['subject'] == template.subject
    assert data['process_type'] == 'normal'
    assert data['service'] == str(template.service_id)
    assert not data['redact_personalisation']
    assert 'folder' in data
    assert 'service_letter_contact' in data
    assert 'template_redacted' in data


@pytest.mark.parametrize(
    'subject, content, path, expected_subject, expected_content, expected_error',
    [
        (
            'about your thing',
            'hello user we’ve received your thing',
            '/service/{}/template/{}/preview',
            'about your thing',
            'hello user we’ve received your thing',
            None,
        ),
        (
            'about your ((thing))',
            'hello ((name)) we’ve received your ((thing))',
            '/service/{}/template/{}/preview?name=Amala&thing=document',
            'about your document',
            'hello Amala we’ve received your document',
            None,
        ),
        (
            'about your ((thing))',
            'hello ((name)) we’ve received your ((thing))',
            '/service/{}/template/{}/preview?name=Amala',
            None,
            None,
            'Missing personalisation: thing',
        ),
        (
            'about your ((thing))',
            'hello ((name)) we’ve received your ((thing))',
            '/service/{}/template/{}/preview?name=Amala&thing=document&foo=bar',
            'about your document',
            'hello Amala we’ve received your document',
            None,
        ),
    ],
)
def test_should_preview_a_single_template(
    client, subject, content, path, expected_subject, expected_content, expected_error, sample_template
):
    template = sample_template(template_type=EMAIL_TYPE, subject=subject, content=content)

    response = client.get(path.format(template.service_id, template.id), headers=[create_admin_authorization_header()])

    content = response.get_json()

    if expected_error:
        assert response.status_code == 400
        assert content['message']['template'] == [expected_error]
    else:
        assert response.status_code == 200
        assert content['content'] == expected_content
        assert content['subject'] == expected_subject


def test_should_return_empty_array_if_no_templates_for_service(client, sample_service):
    auth_header = create_admin_authorization_header()

    response = client.get('/service/{}/template'.format(sample_service().id), headers=[auth_header])

    assert response.status_code == 200
    json_resp = response.get_json()
    assert len(json_resp['data']) == 0


def test_should_return_404_if_no_templates_for_service_with_id(client, sample_service, fake_uuid):
    auth_header = create_admin_authorization_header()

    response = client.get('/service/{}/template/{}'.format(sample_service().id, fake_uuid), headers=[auth_header])

    assert response.status_code == 404
    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'No result found'


def test_create_400_for_over_limit_content(client, notify_db_session, sample_service, sample_user):
    service = sample_service()
    content = ''.join(
        random.choice(string.ascii_uppercase + string.digits)
        for _ in range(SMS_CHAR_COUNT_LIMIT + 1)  # nosec
    )
    data = {
        'name': 'too big template',
        'template_type': SMS_TYPE,
        'content': content,
        'service': str(service.id),
        'created_by': str(sample_user().id),
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    # Requires a context block because the calling method expects current_user in the request
    with client.application.app_context():
        response = client.post(
            '/service/{}/template'.format(service.id),
            headers=[('Content-Type', 'application/json'), auth_header],
            data=data,
        )
    assert response.status_code == 400
    json_resp = response.get_json()
    assert (f'Content has a character count greater than the limit of {SMS_CHAR_COUNT_LIMIT}') in json_resp['message'][
        'content'
    ]

    # Teardown
    template = notify_db_session.session.scalar(select(Template).where(Template.service_id == service.id))
    notify_db_session.session.delete(template)
    notify_db_session.session.commit()


def test_update_400_for_over_limit_content(client, sample_template):
    template = sample_template()
    json_data = json.dumps(
        {
            'content': ''.join(
                random.choice(string.ascii_uppercase + string.digits)
                for _ in range(SMS_CHAR_COUNT_LIMIT + 1)  # nosec
            ),
            'created_by': str(template.created_by_id),
        }
    )
    auth_header = create_admin_authorization_header()
    resp = client.post(
        '/service/{}/template/{}'.format(template.service.id, template.id),
        headers=[('Content-Type', 'application/json'), auth_header],
        data=json_data,
    )
    assert resp.status_code == 400
    json_resp = json.loads(resp.get_data(as_text=True))
    assert ('Content has a character count greater than the limit of {}').format(SMS_CHAR_COUNT_LIMIT) in json_resp[
        'message'
    ]['content']


def test_should_return_all_template_versions_for_service_and_template_id(client, notify_db_session, sample_template):
    template = sample_template()
    original_content = template.content
    from app.dao.templates_dao import dao_update_template

    template.content = original_content + '1'
    dao_update_template(template)

    notify_db_session.session.refresh(template)

    template.content = original_content + '2'
    dao_update_template(template)

    auth_header = create_admin_authorization_header()
    resp = client.get(
        '/service/{}/template/{}/versions'.format(template.service_id, template.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 200
    resp_json = json.loads(resp.get_data(as_text=True))['data']
    assert len(resp_json) == 3
    for x in resp_json:
        if x['version'] == 1:
            assert x['content'] == original_content
        elif x['version'] == 2:
            assert x['content'] == original_content + '1'
        else:
            assert x['content'] == original_content + '2'


def test_update_does_not_create_new_version_when_there_is_no_change(client, sample_template):
    template = sample_template()
    auth_header = create_admin_authorization_header()
    data = {
        'template_type': template.template_type,
        'content': template.content,
    }
    resp = client.post(
        f'/service/{template.service_id}/template/{template.id}',
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 200

    dao_template = dao_get_template_by_id(template.id)
    assert dao_template.version == 1


def test_update_set_process_type_on_template(client, sample_template):
    auth_header = create_admin_authorization_header()
    template = sample_template()
    data = {'process_type': 'priority'}
    resp = client.post(
        '/service/{}/template/{}'.format(template.service_id, template.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert resp.status_code == 200

    template = dao_get_template_by_id(template.id)
    assert template.process_type == 'priority'


def test_update_template_reply_to(client, notify_db_session, sample_template, sample_service):
    service = sample_service(service_permissions=SERVICE_PERMISSION_TYPES)
    template = sample_template(service=service, template_type=LETTER_TYPE, postage='second')

    auth_header = create_admin_authorization_header()
    letter_contact = create_letter_contact(template.service, 'Edinburgh, ED1 1AA')
    data = {
        'reply_to': str(letter_contact.id),
    }

    resp = client.post(
        '/service/{}/template/{}'.format(template.service_id, template.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)

    template = dao_get_template_by_id(template.id)
    assert template.service_letter_contact_id == letter_contact.id

    stmt = select(TemplateHistory).where(TemplateHistory.id == template.id, TemplateHistory.version == 2)
    th = notify_db_session.session.scalars(stmt).one()

    assert th.service_letter_contact_id == letter_contact.id

    # Teardown
    template_histories = notify_db_session.session.scalars(
        select(TemplateHistory).where(TemplateHistory.id == template.id)
    ).all()
    for template in template_histories:
        notify_db_session.session.delete(template)
    notify_db_session.session.commit()


def test_update_template_reply_to_set_to_blank(client, notify_db_session, sample_service, sample_template):
    service = sample_service(service_permissions=['letter'])
    auth_header = create_admin_authorization_header()
    letter_contact = create_letter_contact(service, 'Edinburgh, ED1 1AA')
    template = sample_template(service=service, template_type='letter', reply_to=letter_contact.id)

    data = {
        'reply_to': None,
    }

    resp = client.post(
        '/service/{}/template/{}'.format(template.service_id, template.id),
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)

    template = dao_get_template_by_id(template.id)
    assert template.service_letter_contact_id is None

    stmt = select(TemplateHistory).where(TemplateHistory.id == template.id, TemplateHistory.version == 2)
    th = notify_db_session.session.scalars(stmt).one()

    assert th.service_letter_contact_id is None

    # One of the create methods above generates a template history
    template_history = notify_db_session.session.scalar(
        select(TemplateHistory).where(TemplateHistory.id == template.id)
    )
    notify_db_session.session.delete(template_history)
    notify_db_session.session.commit()


def test_update_redact_template(admin_request, sample_template):
    template = sample_template()
    assert template.redact_personalisation is False

    data = {'redact_personalisation': True, 'created_by': str(template.created_by_id)}

    dt = datetime.now()

    with freeze_time(dt):
        resp = admin_request.post(
            'template.update_template', service_id=template.service_id, template_id=template.id, _data=data
        )

    assert resp is None

    assert template.redact_personalisation is True
    assert template.template_redacted.updated_by_id == template.created_by_id
    assert template.template_redacted.updated_at == dt

    assert template.version == 1


def test_update_redact_template_ignores_other_properties(admin_request, sample_template):
    template = sample_template()
    data = {'name': 'Foo', 'redact_personalisation': True, 'created_by': str(template.created_by_id)}

    admin_request.post('template.update_template', service_id=template.service_id, template_id=template.id, _data=data)

    assert template.redact_personalisation is True
    assert template.name != 'Foo'


def test_update_redact_template_does_nothing_if_already_redacted(admin_request, sample_template):
    template = sample_template()
    dt = datetime.now()
    with freeze_time(dt):
        dao_redact_template(template, template.created_by_id)

    data = {'redact_personalisation': True, 'created_by': str(template.created_by_id)}

    with freeze_time(dt + timedelta(days=1)):
        resp = admin_request.post(
            'template.update_template', service_id=template.service_id, template_id=template.id, _data=data
        )

    assert resp is None

    assert template.redact_personalisation is True
    # make sure that it hasn't been updated
    assert template.template_redacted.updated_at == dt


def test_update_redact_template_400s_if_no_created_by(admin_request, sample_template):
    template = sample_template()
    original_updated_time = template.template_redacted.updated_at
    resp = admin_request.post(
        'template.update_template',
        service_id=template.service_id,
        template_id=template.id,
        _data={'redact_personalisation': True},
        _expected_status=400,
    )

    assert resp == {'result': 'error', 'message': {'created_by': ['Field is required']}}

    assert template.redact_personalisation is False
    assert template.template_redacted.updated_at == original_updated_time


def test_preview_letter_template_by_id_invalid_file_type(admin_request, sample_service, sample_template):
    service = sample_service(service_permissions=SERVICE_PERMISSION_TYPES)
    template = sample_template(service=service, template_type=LETTER_TYPE, postage='second')
    resp = admin_request.get(
        'template.preview_letter_template_by_notification_id',
        service_id=template.service_id,
        template_id=template.id,
        notification_id=template.id,
        file_type='doc',
        _expected_status=400,
    )

    assert ['file_type must be pdf or png'] == resp['message']['content']


def test_should_update_template_with_a_valid_provider(admin_request, sample_template, sample_provider):
    template = sample_template(template_type=EMAIL_TYPE)
    provider = sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    provider_id = str(provider.id)
    data = {'provider_id': provider_id}
    json_resp = admin_request.post(
        'template.update_template',
        service_id=template.service_id,
        template_id=template.id,
        _data=data,
        _expected_status=200,
    )

    assert json_resp['data']['provider_id'] == provider_id

    updated_template = dao_get_template_by_id(template.id)
    assert updated_template.provider_id == provider.id


def test_should_not_update_template_with_non_existent_provider(admin_request, sample_template, fake_uuid):
    template = sample_template(template_type=EMAIL_TYPE)
    data = {'provider_id': fake_uuid}
    admin_request.post(
        'template.update_template',
        service_id=template.service_id,
        template_id=template.id,
        _data=data,
        _expected_status=400,
    )


def test_should_not_update_template_with_non_existent_communication_item(admin_request, sample_template, fake_uuid):
    template = sample_template(template_type=EMAIL_TYPE)
    data = {'communication_item_id': fake_uuid}
    admin_request.post(
        'template.update_template',
        service_id=template.service_id,
        template_id=template.id,
        _data=data,
        _expected_status=400,
    )


@pytest.mark.parametrize('template_type', (EMAIL_TYPE, SMS_TYPE))
def test_should_not_update_template_with_inactive_provider(
    mocker, admin_request, sample_template, fake_uuid, template_type
):
    template = sample_template(template_type=template_type)
    data = {'provider_id': fake_uuid}
    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = False
    mocked_provider_details.notification_type = template_type
    mocked_provider_details.id = fake_uuid
    mocker.patch('app.schemas.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details)

    json_resp = admin_request.post(
        'template.update_template',
        service_id=template.service_id,
        template_id=template.id,
        _data=data,
        _expected_status=400,
    )
    assert json_resp['result'] == 'error'
    assert json_resp['message']['provider_id'][0] == f'Invalid provider id: {fake_uuid}'


def test_should_not_update_template_with_incorrect_provider_type(mocker, admin_request, sample_template, fake_uuid):
    template = sample_template(template_type=EMAIL_TYPE)
    data = {'provider_id': fake_uuid}
    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = True
    mocked_provider_details.notification_type = SMS_TYPE
    mocked_provider_details.id = fake_uuid
    mocker.patch('app.schemas.validate_providers.get_provider_details_by_id', return_value=mocked_provider_details)

    json_resp = admin_request.post(
        'template.update_template',
        service_id=template.service_id,
        template_id=template.id,
        _data=data,
        _expected_status=400,
    )
    assert json_resp['result'] == 'error'
    assert json_resp['message']['provider_id'][0] == f'Invalid provider id: {fake_uuid}'


def test_preview_letter_template_precompiled_pdf_file_type(
    notify_api,
    client,
    admin_request,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
    mocker,
):
    template = sample_template(
        service=sample_service(),
        template_type='letter',
        name='Pre-compiled PDF',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with set_config_values(
        notify_api,
        {
            'TEMPLATE_PREVIEW_API_HOST': 'http://localhost/notifications-template-preview',
            'TEMPLATE_PREVIEW_API_KEY': 'test-key',
        },
    ):
        with requests_mock.Mocker():
            content = b'\x00\x01'

            mock_get_letter_pdf = mocker.patch('app.template.rest.get_letter_pdf', return_value=content)

            resp = admin_request.get(
                'template.preview_letter_template_by_notification_id',
                service_id=notification.service_id,
                notification_id=notification.id,
                file_type='pdf',
            )

            assert mock_get_letter_pdf.called_once_with(notification)
            assert base64.b64decode(resp['content']) == content


def test_preview_letter_template_precompiled_s3_error(
    notify_api,
    client,
    admin_request,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    mocker,
    sample_template,
):
    template = sample_template(
        service=sample_service(),
        template_type='letter',
        name='Pre-compiled PDF',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with set_config_values(
        notify_api,
        {
            'TEMPLATE_PREVIEW_API_HOST': 'http://localhost/notifications-template-preview',
            'TEMPLATE_PREVIEW_API_KEY': 'test-key',
        },
    ):
        with requests_mock.Mocker():
            mocker.patch(
                'app.template.rest.get_letter_pdf',
                side_effect=botocore.exceptions.ClientError(
                    {'Error': {'Code': '403', 'Message': 'Unauthorized'}}, 'GetObject'
                ),
            )

            request = admin_request.get(
                'template.preview_letter_template_by_notification_id',
                service_id=notification.service_id,
                notification_id=notification.id,
                file_type='pdf',
                _expected_status=500,
            )

            assert (
                request['message']
                == 'Error extracting requested page from PDF file for notification_id {} type '
                "<class 'botocore.exceptions.ClientError'> An error occurred (403) "
                'when calling the GetObject operation: Unauthorized'.format(notification.id)
            )


@pytest.mark.parametrize(
    'filetype, post_url, overlay',
    [
        ('png', 'precompiled-preview.png', None),
        ('png', 'precompiled/overlay.png?page_number=1', 1),
        ('pdf', 'precompiled/overlay.pdf', 1),
    ],
)
def test_preview_letter_template_precompiled_png_file_type_or_pdf_with_overlay(
    notify_api,
    client,
    admin_request,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    mocker,
    filetype,
    post_url,
    overlay,
    sample_template,
):
    template = sample_template(
        service=sample_service(),
        template_type='letter',
        name='Pre-compiled PDF',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with set_config_values(
        notify_api,
        {
            'TEMPLATE_PREVIEW_API_HOST': 'http://localhost/notifications-template-preview',
            'TEMPLATE_PREVIEW_API_KEY': 'test-key',
        },
    ):
        with requests_mock.Mocker() as request_mock:
            pdf_content = b'\x00\x01'
            expected_returned_content = b'\x00\x02'

            mock_get_letter_pdf = mocker.patch('app.template.rest.get_letter_pdf', return_value=pdf_content)

            mocker.patch('app.template.rest.extract_page_from_pdf', return_value=pdf_content)

            mock_post = request_mock.post(
                'http://localhost/notifications-template-preview/{}'.format(post_url),
                content=expected_returned_content,
                headers={'X-pdf-page-count': '1'},
                status_code=200,
            )

            resp = admin_request.get(
                'template.preview_letter_template_by_notification_id',
                service_id=notification.service_id,
                notification_id=notification.id,
                file_type=filetype,
                overlay=overlay,
            )

            with pytest.raises(ValueError):
                mock_post.last_request.json()
            assert mock_get_letter_pdf.called_once_with(notification)
            assert base64.b64decode(resp['content']) == expected_returned_content


@pytest.mark.parametrize(
    'page_number,expect_preview_url',
    [
        ('', 'http://localhost/notifications-template-preview/precompiled-preview.png?hide_notify=true'),
        ('1', 'http://localhost/notifications-template-preview/precompiled-preview.png?hide_notify=true'),
        ('2', 'http://localhost/notifications-template-preview/precompiled-preview.png'),
    ],
)
def test_preview_letter_template_precompiled_png_file_type_hide_notify_tag_only_on_first_page(
    notify_api,
    client,
    admin_request,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    mocker,
    page_number,
    expect_preview_url,
    sample_template,
):
    template = sample_template(
        service=sample_service(),
        template_type='letter',
        name='Pre-compiled PDF',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with set_config_values(
        notify_api,
        {
            'TEMPLATE_PREVIEW_API_HOST': 'http://localhost/notifications-template-preview',
            'TEMPLATE_PREVIEW_API_KEY': 'test-key',
        },
    ):
        pdf_content = b'\x00\x01'
        png_content = b'\x00\x02'
        encoded = base64.b64encode(png_content).decode('utf-8')

        mocker.patch('app.template.rest.get_letter_pdf', return_value=pdf_content)
        mocker.patch('app.template.rest.extract_page_from_pdf', return_value=png_content)
        mock_get_png_preview = mocker.patch('app.template.rest._get_png_preview_or_overlaid_pdf', return_value=encoded)

        admin_request.get(
            'template.preview_letter_template_by_notification_id',
            service_id=notification.service_id,
            notification_id=notification.id,
            file_type='png',
            page=page_number,
        )

        mock_get_png_preview.assert_called_once_with(expect_preview_url, encoded, notification.id, json=False)


def test_preview_letter_template_precompiled_png_template_preview_500_error(
    notify_api,
    client,
    admin_request,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    mocker,
    sample_template,
):
    template = sample_template(
        service=sample_service(),
        template_type='letter',
        name='Pre-compiled PDF',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with set_config_values(
        notify_api,
        {
            'TEMPLATE_PREVIEW_API_HOST': 'http://localhost/notifications-template-preview',
            'TEMPLATE_PREVIEW_API_KEY': 'test-key',
        },
    ):
        with requests_mock.Mocker() as request_mock:
            pdf_content = b'\x00\x01'
            png_content = b'\x00\x02'

            mocker.patch('app.template.rest.get_letter_pdf', return_value=pdf_content)

            mocker.patch('app.template.rest.extract_page_from_pdf', return_value=pdf_content)

            mock_post = request_mock.post(
                'http://localhost/notifications-template-preview/precompiled-preview.png',
                content=png_content,
                headers={'X-pdf-page-count': '1'},
                status_code=500,
            )

            admin_request.get(
                'template.preview_letter_template_by_notification_id',
                service_id=notification.service_id,
                notification_id=notification.id,
                file_type='png',
                _expected_status=500,
            )

            with pytest.raises(ValueError):
                mock_post.last_request.json()


def test_preview_letter_template_precompiled_png_template_preview_400_error(
    notify_api,
    client,
    admin_request,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    mocker,
    sample_template,
):
    template = sample_template(
        service=sample_service(),
        template_type='letter',
        name='Pre-compiled PDF',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with set_config_values(
        notify_api,
        {
            'TEMPLATE_PREVIEW_API_HOST': 'http://localhost/notifications-template-preview',
            'TEMPLATE_PREVIEW_API_KEY': 'test-key',
        },
    ):
        with requests_mock.Mocker() as request_mock:
            pdf_content = b'\x00\x01'
            png_content = b'\x00\x02'

            mocker.patch('app.template.rest.get_letter_pdf', return_value=pdf_content)

            mocker.patch('app.template.rest.extract_page_from_pdf', return_value=pdf_content)

            mock_post = request_mock.post(
                'http://localhost/notifications-template-preview/precompiled-preview.png',
                content=png_content,
                headers={'X-pdf-page-count': '1'},
                status_code=404,
            )

            admin_request.get(
                'template.preview_letter_template_by_notification_id',
                service_id=notification.service_id,
                notification_id=notification.id,
                file_type='png',
                _expected_status=500,
            )

            with pytest.raises(ValueError):
                mock_post.last_request.json()


def test_preview_letter_template_precompiled_png_template_preview_pdf_error(
    notify_api,
    client,
    admin_request,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    mocker,
    sample_template,
):
    template = sample_template(
        service=sample_service(),
        template_type='letter',
        name='Pre-compiled PDF',
        subject='Pre-compiled PDF',
        hidden=True,
    )

    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with set_config_values(
        notify_api,
        {
            'TEMPLATE_PREVIEW_API_HOST': 'http://localhost/notifications-template-preview',
            'TEMPLATE_PREVIEW_API_KEY': 'test-key',
        },
    ):
        with requests_mock.Mocker() as request_mock:
            pdf_content = b'\x00\x01'
            png_content = b'\x00\x02'

            mocker.patch('app.template.rest.get_letter_pdf', return_value=pdf_content)

            error_message = 'PDF Error message'
            mocker.patch('app.template.rest.extract_page_from_pdf', side_effect=PdfReadError(error_message))

            request_mock.post(
                'http://localhost/notifications-template-preview/precompiled-preview.png',
                content=png_content,
                headers={'X-pdf-page-count': '1'},
                status_code=404,
            )

            request = admin_request.get(
                'template.preview_letter_template_by_notification_id',
                service_id=notification.service_id,
                notification_id=notification.id,
                file_type='png',
                _expected_status=500,
            )

            assert request[
                'message'
            ] == 'Error extracting requested page from PDF file for notification_id {} type {} {}'.format(
                notification.id, type(PdfReadError()), error_message
            )


def test_should_create_template_without_created_by_using_current_user_id(
    client,
    notify_db_session,
    sample_service,
):
    service = sample_service(
        service_name=f'sample service full permissions {uuid.uuid4()}',
        service_permissions=set(SERVICE_PERMISSION_TYPES),
        check_if_service_exists=False,
    )
    user = service.users[0]
    permission_dao.set_user_service_permission(
        user, service, [Permission(service_id=service.id, user_id=user.id, permission=EDIT_TEMPLATES)]
    )

    data = {
        'name': 'my template',
        'template_type': SMS_TYPE,
        'content': 'template <b>content</b>',
        'service': str(service.id),
        'created_by': None,
    }
    data = json.dumps(data)

    response = client.post(
        '/service/{}/template'.format(service.id),
        headers=[('Content-Type', 'application/json'), ('Authorization', f'Bearer {create_access_token(user)}')],
        data=data,
    )
    assert response.status_code == 201
    json_resp = response.get_json()
    assert json_resp['data']['created_by'] == str(user.id)

    template = notify_db_session.session.get(Template, json_resp['data']['id'])
    from app.schemas import template_schema

    assert sorted(json_resp['data']) == sorted(template_schema.dump(template))

    # Teardown
    stmt = select(TemplateHistory).where(TemplateHistory.service_id == template.service_id)
    for history in notify_db_session.session.scalars(stmt).all():
        notify_db_session.session.delete(history)
    template_redacted = notify_db_session.session.get(TemplateRedacted, template.id)
    notify_db_session.session.delete(template_redacted)
    notify_db_session.session.delete(template)
    notify_db_session.session.commit()


class TestGenerateHtmlPreviewForContent:
    def test_should_generate_html_preview_for_content(
        self,
        client,
        sample_service,
        sample_user,
    ):
        user = sample_user(platform_admin=True)
        token = create_access_token(user)

        response = client.post(
            url_for('template.generate_html_preview_for_content', service_id=sample_service().id),
            data=json.dumps({'content': 'Foo'}),
            headers=[('Content-Type', 'application/json'), ('Authorization', f'Bearer {token}')],
        )

        expected_preview_html = HTMLEmailTemplate({'content': 'Foo', 'subject': ''}, values={}, preview_mode=True)

        assert response.data.decode('utf-8') == str(expected_preview_html)
        assert response.headers['Content-type'] == 'text/html; charset=utf-8'


class TestGenerateHtmlPreviewForTemplateContent:
    def test_should_generate_html_preview_for_template_content(
        self,
        client,
        sample_service,
        sample_user,
    ):
        user = sample_user(platform_admin=True)
        token = create_access_token(user)

        response = client.post(
            url_for('template.generate_html_preview_for_template_content', service_id=sample_service().id),
            data=json.dumps({'content': 'Foo'}),
            headers=[('Content-Type', 'application/json'), ('Authorization', f'Bearer {token}')],
        )

        expected_preview_html = HTMLEmailTemplate({'content': 'Foo', 'subject': ''}, values={}, preview_mode=True)

        assert response.data.decode('utf-8') == str(expected_preview_html)
        assert response.headers['Content-type'] == 'text/html; charset=utf-8'


class TestTemplateNameAlreadyExists:
    def test_create_template_should_return_400_if_template_name_already_exists_on_service(
        self,
        mocker,
        client,
        sample_service,
        sample_user,
    ):
        service = sample_service()
        mock_feature_flag(mocker, FeatureFlag.CHECK_TEMPLATE_NAME_EXISTS_ENABLED, 'True')
        mocker.patch('app.template.rest.template_name_already_exists_on_service', return_value=True)

        data = {
            'name': 'my template',
            'template_type': EMAIL_TYPE,
            'content': 'template <b>content</b>',
            'service': str(service.id),
            'created_by': str(sample_user().id),
            'subject': 'subject',
        }

        data = json.dumps(data)
        auth_header = create_admin_authorization_header()

        # Requires a context block because the calling method expects current_user in the request
        with client.application.app_context():
            response = client.post(
                f'/service/{service.id}/template',
                headers=[('Content-Type', 'application/json'), auth_header],
                data=data,
            )

        assert response.status_code == 400
        assert (
            json.loads(response.data)['message']['content'][0]
            == 'Template name already exists in service. Please change template name.'
        )

    def test_update_should_not_update_a_template_if_name_already_exists(
        self,
        mocker,
        client,
        sample_service,
        sample_template,
    ):
        mock_feature_flag(mocker, FeatureFlag.CHECK_TEMPLATE_NAME_EXISTS_ENABLED, 'True')
        mocker.patch('app.template.rest.template_name_already_exists_on_service', return_value=True)

        service = sample_service(service_permissions=[EMAIL_TYPE])
        template = sample_template(service=service, template_type=EMAIL_TYPE)
        data = {'name': template.name}
        data = json.dumps(data)
        auth_header = create_admin_authorization_header()

        update_response = client.post(
            f'/service/{service.id}/template/{template.id}',
            headers=[('Content-Type', 'application/json'), auth_header],
            data=data,
        )

        assert update_response.status_code == 400
        assert (
            json.loads(update_response.data)['message']['content'][0]
            == 'Template name already exists in service. Please change template name.'
        )


class TestServiceTemplateUsageStats:
    def test_get_specific_template_usage_stats(
        self,
        admin_request,
        sample_ft_notification_status,
        sample_service,
        sample_template,
        sample_job,
    ):
        service = sample_service(service_name=str(uuid.uuid4()), smtp_user='foo')
        template = sample_template(service=service)
        job = sample_job(template)

        sample_ft_notification_status(date(2021, 3, 15), job)
        sample_ft_notification_status(date(2021, 3, 17), job)
        sample_ft_notification_status(date(2021, 10, 10), job, notification_status='sent')
        sample_ft_notification_status(date(2021, 10, 10), job, notification_status='permanent_failure')

        resp = admin_request.get(
            'template.get_specific_template_usage_stats', service_id=service.id, template_id=template.id
        )

        assert resp['data'] == {'delivered': 2, 'permanent_failure': 1, 'sent': 1}

    @freeze_time('2021-10-18 14:00')
    def test_get_specific_template_usage_with_start_date(
        self,
        admin_request,
        sample_ft_notification_status,
        sample_service,
        sample_template,
        sample_job,
    ):
        service = sample_service(service_name=str(uuid.uuid4()), smtp_user='foo')
        template = sample_template(service=service)
        job = sample_job(template)

        sample_ft_notification_status(date(2021, 3, 15), job)
        sample_ft_notification_status(date(2021, 3, 17), job)
        sample_ft_notification_status(date(2021, 10, 10), job, notification_status='sent')
        sample_ft_notification_status(date(2021, 10, 10), job, notification_status='permanent_failure')

        resp = admin_request.get(
            'template.get_specific_template_usage_stats',
            service_id=service.id,
            template_id=template.id,
            start_date=date(2021, 3, 16),
        )

        assert resp['data'] == {'delivered': 1, 'permanent_failure': 1, 'sent': 1}

    @freeze_time('2021-10-18 14:00')
    def test_get_specific_template_usage_with_end_date(
        self,
        admin_request,
        sample_ft_notification_status,
        sample_service,
        sample_template,
        sample_job,
    ):
        service = sample_service(service_name=str(uuid.uuid4()), smtp_user='foo')
        template = sample_template(service=service)
        job = sample_job(template)

        sample_ft_notification_status(date(2021, 3, 15), job)
        sample_ft_notification_status(date(2021, 3, 17), job)
        sample_ft_notification_status(date(2021, 10, 10), job, notification_status='sent')
        sample_ft_notification_status(date(2021, 10, 10), job, notification_status='permanent_failure')

        resp = admin_request.get(
            'template.get_specific_template_usage_stats',
            service_id=service.id,
            template_id=template.id,
            end_date=date(2021, 3, 18),
        )

        assert resp['data'] == {'delivered': 2}

    @freeze_time('2021-10-18 14:00')
    def test_get_specific_template_usage_with_start_and_end_date(
        self,
        admin_request,
        sample_ft_notification_status,
        sample_service,
        sample_template,
        sample_job,
    ):
        service = sample_service(service_name=str(uuid.uuid4()), smtp_user='foo')
        template = sample_template(service=service)
        job = sample_job(template)

        sample_ft_notification_status(date(2021, 3, 15), job)
        sample_ft_notification_status(date(2021, 3, 17), job)
        sample_ft_notification_status(date(2021, 10, 10), job, notification_status='sent')
        sample_ft_notification_status(date(2021, 10, 12), job, notification_status='permanent_failure')

        resp = admin_request.get(
            'template.get_specific_template_usage_stats',
            service_id=service.id,
            template_id=template.id,
            start_date=date(2021, 3, 17),
            end_date=date(2021, 10, 11),
        )

        assert resp['data'] == {'delivered': 1, 'sent': 1}

import pytest
from app.constants import DATETIME_FORMAT, EMAIL_TYPE, SMS_TYPE, TEMPLATE_TYPES
from flask import json
from tests import create_authorization_header

valid_version_params = [None, 1]


@pytest.mark.parametrize(
    'tmp_type',
    [
        SMS_TYPE,
        EMAIL_TYPE,
    ],
)
@pytest.mark.parametrize('version', valid_version_params)
def test_get_template_by_id_returns_200(
    client,
    sample_api_key,
    tmp_type,
    version,
    sample_template,
):
    api_key = sample_api_key()
    template = sample_template(service=api_key.service, template_type=tmp_type)
    auth_header = create_authorization_header(api_key)

    # Version does not store updated_at
    version_path = '/version/{}'.format(version) if version else ''
    response = client.get(
        path='/v2/template/{}{}'.format(template.id, version_path),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'

    json_response = json.loads(response.get_data(as_text=True))

    expected_response = {
        'id': '{}'.format(template.id),
        'type': '{}'.format(template.template_type),
        'created_at': template.created_at.strftime(DATETIME_FORMAT),
        'updated_at': template.updated_at.strftime(DATETIME_FORMAT) if version is None else None,
        'version': template.version,
        'created_by': template.created_by.email_address,
        'body': template.content,
        'html': None,
        'plain_text': None,
        'subject': template.subject,
        'name': template.name,
        'personalisation': {},
        'postage': template.postage,
    }

    assert json_response == expected_response


@pytest.mark.parametrize(
    'create_template_args, expected_personalisation',
    [
        (
            {
                'template_type': SMS_TYPE,
                'content': 'Hello ((placeholder)) ((conditional??yes))',
            },
            {
                'placeholder': {'required': True},
                'conditional': {'required': True},
            },
        ),
        (
            {
                'template_type': EMAIL_TYPE,
                'subject': '((subject))',
                'content': '((content))',
            },
            {
                'subject': {'required': True},
                'content': {'required': True},
            },
        ),
    ],
)
@pytest.mark.parametrize('version', valid_version_params)
def test_get_template_by_id_returns_placeholders(
    client,
    sample_api_key,
    sample_template,
    version,
    create_template_args,
    expected_personalisation,
):
    api_key = sample_api_key()
    template = sample_template(service=api_key.service, **create_template_args)

    auth_header = create_authorization_header(api_key)

    version_path = '/version/{}'.format(version) if version else ''

    response = client.get(
        path='/v2/template/{}{}'.format(template.id, version_path),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = json.loads(response.get_data(as_text=True))
    assert json_response['personalisation'] == expected_personalisation


def test_get_template_with_non_existent_template_id_returns_404(
    client,
    fake_uuid,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    response = client.get(
        path='/v2/template/{}'.format(fake_uuid), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 404
    assert response.headers['Content-type'] == 'application/json'

    json_response = json.loads(response.get_data(as_text=True))

    assert json_response == {'errors': [{'error': 'NoResultFound', 'message': 'No result found'}], 'status_code': 404}


@pytest.mark.parametrize('tmp_type', TEMPLATE_TYPES)
def test_get_template_with_non_existent_version_returns_404(
    client,
    sample_api_key,
    sample_template,
    tmp_type,
):
    api_key = sample_api_key()
    template = sample_template(service=api_key.service, template_type=tmp_type)

    auth_header = create_authorization_header(api_key)

    invalid_version = template.version + 1

    response = client.get(
        path='/v2/template/{}/version/{}'.format(template.id, invalid_version),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 404
    assert response.headers['Content-type'] == 'application/json'

    json_response = json.loads(response.get_data(as_text=True))

    assert json_response == {'errors': [{'error': 'NoResultFound', 'message': 'No result found'}], 'status_code': 404}

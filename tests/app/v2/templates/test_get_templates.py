import pytest
from app.models import EMAIL_TYPE
from flask import json
from itertools import product
from tests import create_authorization_header
from tests.app.conftest import TEMPLATE_TYPES
from uuid import uuid4


def test_get_all_templates_returns_200(
    client,
    sample_api_key,
    sample_template,
):
    api_key = sample_api_key()
    templates = [
        sample_template(
            service=api_key.service,
            template_type=tmp_type,
            subject='subject_{}'.format(name) if tmp_type == EMAIL_TYPE else '',
            name=name,
        )
        for name, tmp_type in product((f'A {uuid4()}', f'B {uuid4()}', f'C {uuid4()}'), TEMPLATE_TYPES)
    ]

    auth_header = create_authorization_header(api_key)

    response = client.get(path='/v2/templates', headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'

    json_response = json.loads(response.get_data(as_text=True))

    assert len(json_response['templates']) == len(templates)

    for index, template in enumerate(json_response['templates']):
        assert template['id'] == str(templates[index].id)
        assert template['body'] == templates[index].content
        assert template['type'] == templates[index].template_type
        if templates[index].template_type == EMAIL_TYPE:
            assert template['subject'] == templates[index].subject


@pytest.mark.parametrize('tmp_type', TEMPLATE_TYPES)
def test_get_all_templates_for_valid_type_returns_200(
    client,
    sample_api_key,
    sample_template,
    tmp_type,
):
    api_key = sample_api_key()
    templates = [
        sample_template(
            service=api_key.service,
            template_type=tmp_type,
            name=f'Template {i}_{uuid4()}',
            subject='subject_{}'.format(i) if tmp_type == EMAIL_TYPE else '',
        )
        for i in range(3)
    ]

    auth_header = create_authorization_header(api_key)

    response = client.get(
        path='/v2/templates?type={}'.format(tmp_type), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'

    json_response = json.loads(response.get_data(as_text=True))

    assert len(json_response['templates']) == len(templates)

    for index, template in enumerate(json_response['templates']):
        assert template['id'] == str(templates[index].id)
        assert template['body'] == templates[index].content
        assert template['type'] == tmp_type
        if templates[index].template_type == EMAIL_TYPE:
            assert template['subject'] == templates[index].subject


@pytest.mark.parametrize('tmp_type', TEMPLATE_TYPES)
def test_get_correct_num_templates_for_valid_type_returns_200(
    client,
    sample_api_key,
    sample_template,
    tmp_type,
):
    api_key = sample_api_key()
    num_templates = 3

    templates = []
    for _ in range(num_templates):
        templates.append(sample_template(service=api_key.service, template_type=tmp_type))

    for other_type in TEMPLATE_TYPES:
        if other_type != tmp_type:
            templates.append(sample_template(service=api_key.service, template_type=other_type))

    auth_header = create_authorization_header(api_key)

    response = client.get(
        path='/v2/templates?type={}'.format(tmp_type), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 200

    json_response = json.loads(response.get_data(as_text=True))

    assert len(json_response['templates']) == num_templates


def test_get_all_templates_for_invalid_type_returns_400(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())

    invalid_type = 'coconut'

    response = client.get(
        path='/v2/templates?type={}'.format(invalid_type), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    json_response = json.loads(response.get_data(as_text=True))

    assert json_response == {
        'status_code': 400,
        'errors': [{'message': 'type coconut is not one of [sms, email, letter]', 'error': 'ValidationError'}],
    }

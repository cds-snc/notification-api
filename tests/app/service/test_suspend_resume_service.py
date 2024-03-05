import uuid

import pytest

from tests import create_admin_authorization_header


@pytest.mark.parametrize('endpoint', ['suspend', 'resume'])
def test_only_allows_post(client, endpoint):
    auth_header = create_admin_authorization_header()
    response = client.get('/service/{}/{}'.format(uuid.uuid4(), endpoint), headers=[auth_header])
    assert response.status_code == 405


@pytest.mark.parametrize('endpoint', ['suspend', 'resume'])
def test_returns_404_when_service_does_not_exist(client, endpoint):
    auth_header = create_admin_authorization_header()
    response = client.post('/service/{}/{}'.format(uuid.uuid4(), endpoint), headers=[auth_header])
    assert response.status_code == 404


@pytest.mark.parametrize('action, active', [('suspend', False), ('resume', True)])
def test_has_not_effect_when_service_is_already_that_state(client, sample_service, action, active, mocker):
    service = sample_service()
    mocked = mocker.patch('app.service.rest.dao_{}_service'.format(action))
    service.active = active
    auth_header = create_admin_authorization_header()
    response = client.post('/service/{}/{}'.format(service.id, action), headers=[auth_header])
    assert response.status_code == 204
    mocked.assert_not_called()
    assert service.active == active

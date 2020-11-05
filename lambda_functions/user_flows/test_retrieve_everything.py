import pytest
from steps import get_api_health_status
from steps import get_authenticated_request
from steps import get_service_id
from steps import get_template_id
from steps import send_email


@pytest.fixture(scope="function")
def environment(pytestconfig):
    return pytestconfig.getoption("environment")


@pytest.fixture(scope="function")
def services(environment):
    return get_authenticated_request(environment, "/service")


@pytest.fixture(scope="function")
def service_id(services):
    return get_service_id(services.json()['data'])


@pytest.fixture(scope="function")
def templates(environment, service_id):
    return get_authenticated_request(environment, "/service/" + service_id + "/template")


@pytest.fixture(scope="function")
def template_id(service_id, templates):
    return get_template_id(templates.json()['data'], service_id)


def test_api_healthy(environment):
    assert get_api_health_status(environment).status_code == 200


def test_get_organizations(environment):
    organizations = get_authenticated_request(environment, "/organisations")
    assert organizations.status_code == 200


def test_get_users(environment):
    users = get_authenticated_request(environment, "/user")
    assert users.status_code == 200


def test_get_services(environment, services):
    assert services.status_code == 200


def test_get_templates(environment, service_id, templates):
    assert templates.status_code == 200


def test_send_email(environment, service_id, template_id):
    email_response = send_email(environment, service_id, template_id)
    assert email_response.status_code == 201

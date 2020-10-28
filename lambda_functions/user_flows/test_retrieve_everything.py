import pytest
from steps import get_authenticated_request
from steps import get_services_id
from steps import get_api_health_status


@pytest.fixture(scope="function")
def environment(pytestconfig):
    return pytestconfig.getoption("environment")


@pytest.fixture(scope="function")
def services(environment):
    return get_authenticated_request(environment, "/service")


def test_get_organizations(environment):
    organizations = get_authenticated_request(environment, "/organisations")
    assert organizations.status_code == 200


def test_get_users(environment):
    users = get_authenticated_request(environment, "/user")
    assert users.status_code == 200


def test_get_services(services, environment):
    assert services.status_code == 200


def test_get_templates(services, environment):
    service_id = get_services_id(services.json()['data'])
    templates = get_authenticated_request(environment, "/service/" + service_id + "/template")
    assert templates.status_code == 200


def test_api_healthy(environment):
    assert get_api_health_status(environment).status_code == 200

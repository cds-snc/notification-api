import pytest
from steps import get_notification_url
from steps import get_api_health_status
from steps import get_authenticated_request
from steps import get_service_id
from steps import get_template_id
from steps import get_user_id
from steps import get_new_service_api_key
from steps import send_email


@pytest.fixture(scope="function")
def environment(pytestconfig):
    return pytestconfig.getoption("environment")


@pytest.fixture(scope="function")
def notification_url(environment):
    return get_notification_url(environment)


@pytest.fixture(scope="function")
def services(environment, notification_url):
    return get_authenticated_request(environment, F"{notification_url}/service")


@pytest.fixture(scope="function")
def service_id(services):
    return get_service_id(services.json()['data'])


@pytest.fixture(scope="function")
def templates(environment, notification_url, service_id):
    return get_authenticated_request(environment, F"{notification_url}/service/{service_id}/template")


@pytest.fixture(scope="function")
def template_id(service_id, templates):
    return get_template_id(templates.json()['data'], service_id)


@pytest.fixture(scope="function")
def users(environment, notification_url):
    return get_authenticated_request(environment, F"{notification_url}/user")


@pytest.fixture(scope="function")
def user_id(service_id, users):
    return get_user_id(service_id, users.json()['data'])


def test_api_healthy(environment, notification_url):
    response = get_api_health_status(environment, F"{notification_url}/_status")
    assert response.status_code == 200


def test_get_organizations(environment, notification_url):
    organizations = get_authenticated_request(environment, F"{notification_url}/organisations")
    assert organizations.status_code == 200


def test_get_users(environment, notification_url, users):
    assert users.status_code == 200


def test_get_services(environment, notification_url, services):
    assert services.status_code == 200


def test_get_templates(environment, notification_url, service_id, templates):
    assert templates.status_code == 200


def test_send_email(environment, notification_url, service_id, template_id, user_id):
    service_key_response = get_new_service_api_key(environment, notification_url, service_id, user_id)
    service_key = service_key_response.json()["data"]
    email_response = send_email(notification_url, service_id, service_key, template_id)
    assert email_response.status_code == 201

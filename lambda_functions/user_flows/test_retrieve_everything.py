import pytest
import time

from requests import Response

from steps import (
    get_notification_url,
    get_admin_jwt,
    get_api_health_status,
    get_authenticated_request,
    get_service_id,
    get_first_email_template_id,
    get_user_id,
    get_new_service_api_key,
    get_new_service_test_api_key,
    get_service_jwt,
    send_email_with_email_address,
    send_email_with_va_profile_id,
    get_notification_id,
    get_notification_status,
    send_email_with_icn,
    send_sms_with_phone_number,
    get_first_sms_template_id,
    send_sms_with_va_profile_id
)

VALID_TEST_RECIPIENT_PHONE_NUMBER = "+16502532222"


@pytest.fixture(scope="function")
def environment(pytestconfig) -> str:
    return pytestconfig.getoption("environment")


@pytest.fixture(scope="function")
def notification_url(environment) -> str:
    return get_notification_url(environment)


@pytest.fixture(scope="function")
def services(environment, notification_url) -> Response:
    jwt_token = get_admin_jwt(environment)
    return get_authenticated_request(F"{notification_url}/service", jwt_token)


@pytest.fixture(scope="function")
def service_id(services) -> str:
    return get_service_id(services.json()['data'])


@pytest.fixture(scope="function")
def get_templates_response(environment, notification_url, service_id) -> Response:
    jwt_token = get_admin_jwt(environment)
    return get_authenticated_request(F"{notification_url}/service/{service_id}/template", jwt_token)


@pytest.fixture(scope="function")
def template_id(get_templates_response) -> str:
    return get_first_email_template_id(get_templates_response.json()['data'])


@pytest.fixture(scope="function")
def sms_template_id(get_templates_response) -> str:
    return get_first_sms_template_id(get_templates_response.json()['data'])


@pytest.fixture(scope="function")
def users(environment, notification_url) -> Response:
    jwt_token = get_admin_jwt(environment)
    return get_authenticated_request(F"{notification_url}/user", jwt_token)


@pytest.fixture(scope="function")
def user_id(service_id, users) -> str:
    return get_user_id(service_id, users.json()['data'])


@pytest.fixture(scope="function")
def service_api_key(environment, notification_url, service_id, user_id) -> str:
    return get_new_service_api_key(environment, notification_url, service_id, user_id)


@pytest.fixture(scope="function")
def service_test_api_key(environment, notification_url, service_id, user_id) -> str:
    return get_new_service_test_api_key(environment, notification_url, service_id, user_id)


def test_api_healthy(environment, notification_url):
    response = get_api_health_status(environment, F"{notification_url}/_status")
    assert response.status_code == 200


def test_get_organizations(environment, notification_url):
    jwt_token = get_admin_jwt(environment)
    organizations = get_authenticated_request(F"{notification_url}/organisations", jwt_token)
    assert organizations.status_code == 200


def test_get_users(environment, notification_url, users):
    assert users.status_code == 200


def test_get_services(environment, notification_url, services):
    assert services.status_code == 200


def test_get_templates(environment, notification_url, service_id, get_templates_response):
    assert get_templates_response.status_code == 200


@pytest.mark.skip(reason="Will re-enable once SES set up is completed (story numbers 288 and 321). Current SES changes impact provider priority, causing clash with Govdelivery test data")
def test_send_email(environment, notification_url, service_id, service_api_key, template_id, user_id):
    service_jwt = get_service_jwt(service_id, service_api_key)
    email_response = send_email_with_email_address(notification_url, service_jwt, template_id)
    assert email_response.status_code == 201
    notification_id = get_notification_id(email_response)
    time_count = 0
    notification_status = ""
    while notification_status != "sending" and time_count < 30:
        service_jwt = get_service_jwt(service_id, service_api_key)
        notification_status_response = get_notification_status(notification_id, notification_url, service_jwt)
        assert notification_status_response.status_code == 200
        notification_status = notification_status_response.json()['status']
        time.sleep(1)
        time_count = time_count + 1
    assert notification_status == 'sending'


def test_send_email_with_va_profile_id(environment, notification_url, service_id, service_test_api_key, template_id, user_id):
    service_jwt = get_service_jwt(service_id, service_test_api_key)

    email_response = send_email_with_va_profile_id(notification_url, service_jwt, template_id)
    assert email_response.status_code == 201
    notification_id = get_notification_id(email_response)

    desired_status = 'delivered'
    notification_status_response = wait_for_status(
        notification_id,
        notification_url,
        service_id,
        service_test_api_key,
        desired_status
    )

    assert notification_status_response.json()['status'] == desired_status
    assert notification_status_response.json()['email_address'] is not None


def test_send_email_with_icn(environment, notification_url, service_id, service_test_api_key, template_id, user_id):
    service_jwt = get_service_jwt(service_id, service_test_api_key)

    email_response = send_email_with_icn(notification_url, service_jwt, template_id)
    assert email_response.status_code == 201
    notification_id = get_notification_id(email_response)

    desired_status = 'delivered'
    notification_status_response = wait_for_status(
        notification_id,
        notification_url,
        service_id,
        service_test_api_key,
        desired_status
    )

    assert notification_status_response.json()['status'] == desired_status
    assert notification_status_response.json()['email_address'] is not None

    found_va_profile_ids = [identifier for identifier in notification_status_response.json()['recipient_identifiers']
                            if identifier['id_type'] == 'VAPROFILEID']
    assert len(found_va_profile_ids) == 1


def test_send_text(notification_url, service_test_api_key, service_id, sms_template_id):
    service_jwt = get_service_jwt(service_id, service_test_api_key)

    sms_response = send_sms_with_phone_number(
        notification_url, service_jwt, sms_template_id, VALID_TEST_RECIPIENT_PHONE_NUMBER
    )
    assert sms_response.status_code == 201
    notification_id = get_notification_id(sms_response)

    desired_status = 'sent'
    notification_status_response = wait_for_status(
        notification_id,
        notification_url,
        service_id,
        service_test_api_key,
        desired_status
    )

    assert notification_status_response.json()['status'] == desired_status
    assert notification_status_response.json()['phone_number'] == VALID_TEST_RECIPIENT_PHONE_NUMBER


def test_send_text_with_profile_id(notification_url, service_test_api_key, service_id, sms_template_id):
    service_jwt = get_service_jwt(service_id, service_test_api_key)

    sms_response = send_sms_with_va_profile_id(notification_url, service_jwt, sms_template_id)
    assert sms_response.status_code == 201
    notification_id = get_notification_id(sms_response)

    desired_status = 'sent'
    notification_status_response = wait_for_status(
        notification_id,
        notification_url,
        service_id,
        service_test_api_key,
        desired_status
    )

    assert notification_status_response.json()['status'] == desired_status
    assert notification_status_response.json()['phone_number'] is not None


def wait_for_status(
        notification_id: str,
        notification_url: str,
        service_id: str,
        service_test_api_key: str,
        desired_status: str
) -> Response:
    notification_status_response = None
    for _ in range(30):
        service_jwt = get_service_jwt(service_id, service_test_api_key)
        notification_status_response = get_notification_status(notification_id, notification_url, service_jwt)

        assert notification_status_response.status_code == 200

        if notification_status_response.json()['status'] == desired_status:
            return notification_status_response

        time.sleep(1)

    pytest.fail(f"Response did not reach desired status '{desired_status}': {notification_status_response.json()}")

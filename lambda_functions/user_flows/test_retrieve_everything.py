import pytest
import time

from requests import Response, get

from steps import (
    get_authenticated_request,
    send_email_with_email_address,
    send_email_with_va_profile_id,
    get_notification_id,
    get_notification_status,
    send_email_with_icn,
    send_sms_with_phone_number,
    send_sms_with_va_profile_id,
    revoke_service_api_keys,
    create_service_api_key,
    encode_jwt,
    get_admin_client_secret
)

VALID_TEST_RECIPIENT_PHONE_NUMBER = "+16502532222"


@pytest.fixture(scope="function")
def environment(pytestconfig) -> str:
    return pytestconfig.getoption("environment")


@pytest.fixture(scope="function")
def notification_url(environment) -> str:
    return f"https://{environment}.api.notifications.va.gov"


@pytest.fixture(scope="function")
def admin_jwt_token(environment) -> bytes:
    return encode_jwt('notify-admin', get_admin_client_secret(environment))


@pytest.fixture(scope="function")
def get_services_response(notification_url, admin_jwt_token) -> Response:
    return get_authenticated_request(F"{notification_url}/service", admin_jwt_token)


@pytest.fixture(scope="function")
def service_id(get_services_response) -> str:
    service = next(
        service for service in get_services_response.json()['data']
        if service['name'] == "User Flows Test Service"
    )
    return service['id']


@pytest.fixture(scope="function")
def get_templates_response(notification_url, admin_jwt_token, service_id) -> Response:
    return get_authenticated_request(F"{notification_url}/service/{service_id}/template", admin_jwt_token)


@pytest.fixture(scope="function")
def template_id(get_templates_response) -> str:
    first_email_template = next(
        template for template in get_templates_response.json()['data']
        if template['template_type'] == 'email'
    )
    return first_email_template["id"]


@pytest.fixture(scope="function")
def sms_template_id(get_templates_response) -> str:
    first_sms_template = next(
        template for template in get_templates_response.json()['data']
        if template['template_type'] == 'sms'
    )
    return first_sms_template["id"]


@pytest.fixture(scope="function")
def get_users_response(notification_url, admin_jwt_token) -> Response:
    return get_authenticated_request(F"{notification_url}/user", admin_jwt_token)


@pytest.fixture(scope="function")
def user_id(service_id, get_users_response) -> str:
    user = next(
        user for user in get_users_response.json()['data']
        if user['name'] == 'Test User' and service_id in user['services']
    )
    return user['id']


@pytest.fixture(scope="function")
def service_api_key(notification_url, admin_jwt_token, service_id, user_id) -> str:
    revoke_service_api_keys(notification_url, admin_jwt_token, service_id)
    return create_service_api_key(notification_url, admin_jwt_token, user_id, "normal", service_id)


@pytest.fixture(scope="function")
def service_test_api_key(notification_url, admin_jwt_token, service_id, user_id) -> str:
    revoke_service_api_keys(notification_url, admin_jwt_token, service_id)
    return create_service_api_key(notification_url, admin_jwt_token, user_id, "test", service_id)


def test_api_healthy(notification_url):
    response = get(F"{notification_url}/_status")
    assert response.status_code == 200


def test_get_organizations(notification_url, admin_jwt_token):
    organizations = get_authenticated_request(F"{notification_url}/organisations", admin_jwt_token)
    assert organizations.status_code == 200


def test_get_users(get_users_response):
    assert get_users_response.status_code == 200


def test_get_services(get_services_response):
    assert get_services_response.status_code == 200


def test_get_templates(get_templates_response):
    assert get_templates_response.status_code == 200


@pytest.mark.skip(reason="Will re-enable once SES set up is completed (story numbers 288 and 321). Current SES changes impact provider priority, causing clash with Govdelivery test data")
def test_send_email(notification_url, service_id, service_api_key, template_id):
    service_jwt = encode_jwt(service_id, service_api_key)
    email_response = send_email_with_email_address(notification_url, service_jwt, template_id)
    assert email_response.status_code == 201
    notification_id = get_notification_id(email_response)
    time_count = 0
    notification_status = ""
    notification_sent_by = None
    while notification_status != "sending" and time_count < 30:
        service_jwt = encode_jwt(service_id, service_api_key)
        notification_status_response = get_notification_status(notification_id, notification_url, service_jwt)
        assert notification_status_response.status_code == 200
        notification_status = notification_status_response.json()['status']
        notification_sent_by = notification_status_response.json()['sent_by']
        time.sleep(1)
        time_count = time_count + 1
    assert notification_status == 'sending'
    assert notification_sent_by is not None


def test_send_email_with_va_profile_id(notification_url, service_id, service_test_api_key, template_id):
    service_jwt = encode_jwt(service_id, service_test_api_key)

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

    assert notification_status_response['status'] == desired_status
    assert notification_status_response['email_address'] is not None
    assert notification_status_response['sent_by'] is not None


def test_send_email_with_icn(notification_url, service_id, service_test_api_key, template_id):
    service_jwt = encode_jwt(service_id, service_test_api_key)

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

    assert notification_status_response['status'] == desired_status
    assert notification_status_response['email_address'] is not None
    assert notification_status_response['sent_by'] is not None

    found_va_profile_ids = [identifier for identifier in notification_status_response.json()['recipient_identifiers']
                            if identifier['id_type'] == 'VAPROFILEID']
    assert len(found_va_profile_ids) == 1


def test_send_text(notification_url, service_test_api_key, service_id, sms_template_id):
    service_jwt = encode_jwt(service_id, service_test_api_key)

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

    assert notification_status_response['status'] == desired_status
    assert notification_status_response['phone_number'] == VALID_TEST_RECIPIENT_PHONE_NUMBER
    assert notification_status_response['sent_by'] is not None


def test_send_text_with_profile_id(notification_url, service_test_api_key, service_id, sms_template_id):
    service_jwt = encode_jwt(service_id, service_test_api_key)

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

    assert notification_status_response['status'] == desired_status
    assert notification_status_response['phone_number'] is not None
    assert notification_status_response['sent_by'] is not None


def wait_for_status(
        notification_id: str,
        notification_url: str,
        service_id: str,
        service_test_api_key: str,
        desired_status: str
) -> dict:
    notification_status_response = None
    for _ in range(30):
        service_jwt = encode_jwt(service_id, service_test_api_key)
        notification_status_response = get_notification_status(notification_id, notification_url, service_jwt)

        assert notification_status_response.status_code == 200

        if notification_status_response.json()['status'] == desired_status:
            return notification_status_response.json()

        time.sleep(1)

    pytest.fail(f"Response did not reach desired status '{desired_status}': {notification_status_response.json()}")

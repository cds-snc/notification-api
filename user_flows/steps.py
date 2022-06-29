import json
import jwt
import os
import requests
import time

NOTIFICATION_URL = os.getenv("NOTIFICATION_URL")
API_SECRET = os.getenv("NOTIFICATION_SECRET")

if API_SECRET is None:
    raise RuntimeError("Missing secret environment variable.")

if NOTIFICATION_URL is None:
    raise RuntimeError("Missing Notification url.")


def get_jwt() -> str:
    """ Return a JWT. """

    currentTimestamp = int(time.time())

    combo = {
        "alg": "HS256",
        "exp": currentTimestamp + 30,
        "iat": currentTimestamp,
        "iss": "notify-admin",
        "jti": "jwt_nonce",
        "typ": "JWT",
    }

    return jwt.encode(combo, API_SECRET, algorithm="HS256")


def get_service_jwt(api_key_secret, service_id) -> str:
    """ Return a JWT for a specific service. """

    combo = {
        "alg": "HS256",
        "iat": int(time.time()),
        "iss": service_id,
        "typ": "JWT",
    }

    return jwt.encode(combo, api_key_secret, algorithm="HS256")


def get_authenticated_request(endpoint):
    return requests.get(
        NOTIFICATION_URL + endpoint,
        headers={"Authorization": "Bearer " + get_jwt()}
    )


def get_status():
    r = requests.get(NOTIFICATION_URL + "/_status")
    return r


def get_organizations():
    return get_authenticated_request("/organisations")


def get_organization_id(data):
    id = data[-1]['id']
    for organization in data:
        if organization['count_of_live_services'] >= 1:
            id = organization['id']
    return id


def get_services():
    return get_authenticated_request("/service")


def get_services_id(data):
    service_id = data[-1]['id']
    for service in data:
        if service['email_from'] == "solutions":
            service_id = service['id']
    return service_id


def get_users():
    return get_authenticated_request("/user")


def get_user_id(users, service_id):
    user_id = users[-1]['id']
    for user in users:
        if service_id in user['services']:
            user_id = user['id']
    return user_id


def get_templates(service_id):
    return get_authenticated_request("/service/" + service_id + "/template")


def get_template_id(templates, service_id):
    template_id = templates[-1]["id"]
    for template in templates:
        if template["service"] == service_id and template["template_type"] == "email":
            template_id = template["id"]
    return template_id


def test_status():
    assert get_status().status_code == 200


def create_api_key(service_id, user_id):
    headers = {
        "Authorization": "Bearer " + get_jwt(),
        "Content-Type": "application/json",
    }

    payload = {
        "created_by": user_id,
        "key_type": "normal",
        "name": "userflows",
    }

    return requests.post(
        NOTIFICATION_URL + "/service/" + service_id + "/api-key",
        headers=headers,
        data=json.dumps(payload)
    )


def get_api_key(service_id):
    return get_authenticated_request("/service/" + service_id + "/api-keys")


def get_right_api_key(get_key_response):
    right_key = get_key_response[-1]["id"]
    for api_key in get_key_response:
        if api_key["name"] == "userflows" and api_key["expiry_date"] is None:
            right_key = api_key["id"]
    return right_key


def revoke_key(old_key_id, service_id):
    headers = {
        "Authorization": "Bearer " + get_jwt(),
        "Content-Type": "application/json",
    }

    url = NOTIFICATION_URL + "/service/" + service_id + "/api-key/revoke/" + old_key_id
    return requests.post(url, headers=headers, data={})


def send_email(the_jwt, template_id):
    headers = {
        "Authorization": "Bearer " + the_jwt,
        "Content-Type": "application/json",
    }

    payload = {
        "template_id": template_id,
        "email_address": "test@sink.govdelivery.com",
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "Test Subject",
        },
    }

    url = NOTIFICATION_URL + "/v2/notifications/email"
    return requests.post(url, headers=headers, data=json.dumps(payload))


def get_notification_id(notification_response):
    return notification_response.json()['id']


def get_notification_status(the_jwt, notification_id):
    headers = {
        "Authorization": "Bearer " + the_jwt,
        "Content-Type": "application/json"
    }

    url = NOTIFICATION_URL + "/v2/notifications/" + notification_id
    return requests.get(url, headers=headers)

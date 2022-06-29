import boto3
import json
import jwt
import requests
import time
from requests import Response

client = boto3.client("ssm")


def get_admin_client_secret(environment: str) -> str:
    response = client.get_parameter(
        Name=f"/{environment}/notification-api/admin-client-secret",
        WithDecryption=True
    )

    api_secret = response.get("Parameter", {}).get("Value")

    if api_secret is None:
        raise RuntimeError("Could not retrieve secret environment variable.")

    return api_secret


def encode_jwt(issuer: str, secret_key: str) -> str:
    """ Return a JWT. """

    current_timestamp = int(time.time())

    combo = {
        "alg": "HS256",
        "exp": current_timestamp + 30,
        "iat": current_timestamp,
        "iss": issuer,
        "jti": "jwt_nonce",
        "typ": "JWT",
    }

    return jwt.encode(combo, secret_key, algorithm="HS256")


def get_authenticated_request(url: str, jwt_token: str) -> Response:
    headers = {
        "Authorization": f"Bearer {jwt_token}",
    }

    return requests.get(url, headers=headers)


def post_authenticated_request(url: str, jwt_token: str, payload: str = "{}") -> Response:
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }

    assert isinstance(payload, str), "Convert the payload to a string before calling this function."
    return requests.post(url, headers=headers, data=payload)


def revoke_service_api_keys(notification_url: str, admin_jwt_token: str, service_id: str) -> None:
    existing_api_keys_response = get_authenticated_request(
        f"{notification_url}/service/{service_id}/api-keys",
        admin_jwt_token
    )

    existing_api_keys = existing_api_keys_response.json()["apiKeys"]
    active_api_keys = [api_key for api_key in existing_api_keys if api_key["expiry_date"] is None]

    for api_key in active_api_keys:
        revoke_url = f"{notification_url}/service/{service_id}/api-key/revoke/{api_key['id']}"
        post_authenticated_request(revoke_url, admin_jwt_token)


def create_service_api_key(notification_url: str, admin_jwt_token: str, user_id: str, key_type: str, service_id: str) -> str:
    post_api_key_payload = json.dumps({
        "created_by": user_id,
        "key_type": key_type,
        "name": f"userflows-key-{key_type}",
    })

    post_api_key_url = f"{notification_url}/service/{service_id}/api-key"
    new_key_response = post_authenticated_request(post_api_key_url, admin_jwt_token, post_api_key_payload).json()

    assert "data" in new_key_response, new_key_response
    return new_key_response["data"]


def send_email(notification_url: str, service_jwt: str, payload: str) -> Response:
    return post_authenticated_request(f"{notification_url}/v2/notifications/email", service_jwt, payload)


def send_sms(notification_url: str, service_jwt: str, payload: str) -> Response:
    return post_authenticated_request(f"{notification_url}/v2/notifications/sms", service_jwt, payload)


def send_email_with_email_address(notification_url: str, service_jwt: str, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "email_address": "test@sink.govdelivery.com",
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "Test Subject",
            "first_name": "Testfirstname",
        },
    })

    return send_email(notification_url, service_jwt, payload)


def send_email_with_va_profile_id(notification_url: str, service_jwt: str, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": "VAPROFILEID",
            "id_value": "1243",
        },
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "VA Profile ID Email",
            "first_name": "VAProfilefirstname",
        },
    })

    return send_email(notification_url, service_jwt, payload)


def send_email_with_icn(notification_url: str, service_jwt: str, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": "ICN",
            "id_value": "1008794780V325793",
        },
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "ICN Email",
            "first_name": "ICNfirstname",
        },
    })

    return send_email(notification_url, service_jwt, payload)


def get_notification_id(notification_response: Response) -> str:
    return notification_response.json()['id']


def get_notification_status(notification_id: str, notification_url: str, service_jwt: str) -> Response:
    return get_authenticated_request(f"{notification_url}/v2/notifications/{notification_id}", service_jwt)


def send_sms_with_phone_number(notification_url: str, service_jwt: str, template_id: str, recipient_number: str) -> Response:
    payload = json.dumps({
        "phone_number": recipient_number,
        "template_id": template_id,
    })

    return send_sms(notification_url, service_jwt, payload)


def send_sms_with_va_profile_id(notification_url: str, service_jwt: str, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": "VAPROFILEID",
            "id_value": "203",
        },
    })

    return send_sms(notification_url, service_jwt, payload)

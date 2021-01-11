import requests
import json
import jwt
import time
import boto3
from jwt import PyJWT

client = boto3.client('ssm')


def get_api_secret(environment):
    key = "/{env}/notification-api/admin-client-secret".format(env=environment)
    resp = client.get_parameter(
        Name=key,
        WithDecryption=True
    )
    api_secret = resp["Parameter"]["Value"]

    if(not api_secret):
        raise ValueError("Could not retrieve secret environment variable")

    return api_secret


def get_jwt(environment):
    jwt_secret = get_api_secret(environment)
    header = {'typ': 'JWT', 'alg': 'HS256'}
    combo = {}
    current_timestamp = int(time.time())
    data = {
        'iss': "notify-admin",
        'iat': current_timestamp,
        'exp': current_timestamp + 30,
        'jti': 'jwt_nonce'
    }
    combo.update(data)
    combo.update(header)
    encoded_jwt = jwt.encode(combo, jwt_secret, algorithm='HS256')
    return encoded_jwt


def get_notification_url(environment):
    return "https://{env}.api.notifications.va.gov".format(env=environment)


def get_authenticated_request(environment, url):
    jwt = get_jwt(environment)
    header = {"Authorization": F"Bearer {jwt.decode('utf-8')}"}
    r = requests.get(url, headers=header)
    return r


def post_authenticated_request(environment, url, payload={}):
    jwt = get_jwt(environment)
    header = {"Authorization": F"Bearer {jwt.decode('utf-8')}", 'Content-Type': 'application/json'}
    return requests.post(url, headers=header, data=payload)


def get_api_health_status(environment, url):
    return requests.get(url)


def get_organization_id(data):
    organization_id = data[-1]['id']
    for organization in data:
        if organization['count_of_live_services'] >= 1:
            organization_id = organization['id']
    return organization_id


def get_service_id(services):
    service = next(service for service in services if service['name'] == "User Flows Test Service")
    return service['id']


def get_user_id(service_id, users):
    user = next(user for user in users if user['name'] == 'Test User' and service_id in user['services'])
    return user['id']


def get_first_email_template_id(templates):
    first_email_template = next(template for template in templates if template['template_type'] == 'email')
    return first_email_template["id"]


def get_first_sms_template_id(templates):
    first_sms_template = next(template for template in templates if template['template_type'] == 'sms')
    return first_sms_template["id"]


def revoke_service_api_keys(environment, notification_url, service_id):
    existing_api_keys_response = get_authenticated_request(environment, F"{notification_url}/service/{service_id}/api-keys")
    existing_api_keys = existing_api_keys_response.json()['apiKeys']
    active_api_keys = [api_key for api_key in existing_api_keys if api_key["expiry_date"] is None]

    for api_key in active_api_keys:
        revoke_url = F"{notification_url}/service/{service_id}/api-key/revoke/{api_key['id']}"
        post_authenticated_request(environment, revoke_url)


def create_service_api_key(environment, notification_url, service_id, user_id):
    jwt = get_jwt(environment)
    header = {"Authorization": F"Bearer {jwt.decode('utf-8')}", 'Content-Type': 'application/json'}
    post_api_key_payload = json.dumps({
        "created_by": user_id,
        "key_type": "normal",
        "name": "userflows"
    })
    post_api_key_url = F"{notification_url}/service/{service_id}/api-key"
    new_key_response = requests.post(post_api_key_url, headers=header, data=post_api_key_payload)
    return new_key_response.json()['data']


def create_service_test_api_key(environment, notification_url, service_id, user_id):
    jwt = get_jwt(environment)
    header = {"Authorization": F"Bearer {jwt.decode('utf-8')}", 'Content-Type': 'application/json'}
    post_api_key_payload = json.dumps({
        "created_by": user_id,
        "key_type": "test",
        "name": "userflows-test"
    })
    post_api_key_url = F"{notification_url}/service/{service_id}/api-key"
    new_key_response = requests.post(post_api_key_url, headers=header, data=post_api_key_payload)
    return new_key_response.json()['data']


def get_new_service_api_key(environment, notification_url, service_id, user_id):
    revoke_service_api_keys(environment, notification_url, service_id)
    return create_service_api_key(environment, notification_url, service_id, user_id)


def get_new_service_test_api_key(environment, notification_url, service_id, user_id):
    revoke_service_api_keys(environment, notification_url, service_id)
    return create_service_test_api_key(environment, notification_url, service_id, user_id)


def get_service_jwt(api_key_secret, service_id):
    jwt_secret = api_key_secret
    header = {'typ': 'JWT', 'alg': 'HS256'}
    combo = {}
    current_timestamp = int(time.time())
    data = {
        'iss': service_id,
        'iat': current_timestamp,
    }
    combo.update(data)
    combo.update(header)
    encoded_jwt = jwt.encode(combo, jwt_secret, algorithm='HS256')
    return encoded_jwt


def send_email(notification_url, service_jwt, payload):
    header = {"Authorization": F"Bearer {service_jwt.decode('utf-8')}", 'Content-Type': 'application/json'}
    post_url = F"{notification_url}/v2/notifications/email"
    return requests.post(post_url, headers=header, data=payload)


def send_email_with_email_address(notification_url, service_jwt, template_id):
    payload = json.dumps({
        "template_id": template_id,
        "email_address": "test@sink.govdelivery.com",
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "Test Subject"
        }
    })
    return send_email(notification_url, service_jwt, payload)


def send_email_with_va_profile_id(notification_url, service_jwt, template_id):
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": 'VAPROFILEID',
            "id_value": "1243"
        },
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "VA Profile ID Email"
        }
    })
    return send_email(notification_url, service_jwt, payload)


def send_email_with_icn(notification_url, service_jwt, template_id):
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": 'ICN',
            "id_value": "1008794780V325793"
        },
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "ICN Email"
        }
    })
    return send_email(notification_url, service_jwt, payload)


def get_notification_id(notification_response):
    return notification_response.json()['id']


def get_notification_status(notification_id, notification_url, service_jwt):
    header = {"Authorization": "Bearer " + service_jwt.decode("utf-8"), 'Content-Type': 'application/json'}
    url = F"{notification_url}/v2/notifications/{notification_id}"
    return requests.get(url, headers=header)


def send_sms_with_phone_number(notification_url: str, service_jwt: PyJWT, template_id: str, recipient_number: str):
    payload = json.dumps({
        "phone_number": recipient_number,
        "template_id": template_id
    })

    return send_sms(notification_url, service_jwt, payload)


def send_sms_with_va_profile_id(notification_url: str, service_jwt: PyJWT, template_id: str):
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": 'VAPROFILEID',
            "id_value": "203"
        }
    })
    return send_sms(notification_url, service_jwt, payload)


def send_sms(notification_url: str, service_jwt: PyJWT, payload: str):
    header = {"Authorization": F"Bearer {service_jwt.decode('utf-8')}", 'Content-Type': 'application/json'}
    post_url = F"{notification_url}/v2/notifications/sms"
    return requests.post(post_url, headers=header, data=payload)

import requests
# import json
import jwt
import time
import boto3


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
    jwtSecret = get_api_secret(environment)
    header = {'typ': 'JWT', 'alg': 'HS256'}
    combo = {}
    currentTimestamp = int(time.time())
    data = {
        'iss': "notify-admin",
        'iat': currentTimestamp,
        'exp': currentTimestamp + 30,
        'jti': 'jwt_nonce'
    }
    combo.update(data)
    combo.update(header)
    encoded_jwt = jwt.encode(combo, jwtSecret, algorithm='HS256')
    return encoded_jwt


def get_notification_url(environment):
    return "https://{env}.api.notifications.va.gov".format(env=environment)


def get_authenticated_request(environment, endpoint):
    notification_url = get_notification_url(environment)
    jwt = get_jwt(environment)
    header = {"Authorization": "Bearer " + jwt.decode("utf-8")}
    r = requests.get(notification_url + endpoint, headers=header)
    return r


def get_api_health_status(environment):
    notification_url = get_notification_url(environment)
    r = requests.get(notification_url + "/_status")
    return r


def get_organization_id(data):
    id = data[-1]['id']
    for organization in data:
        if organization['count_of_live_services'] >= 1:
            id = organization['id']
    return id


def get_services_id(data):
    service_id = data[-1]['id']
    for service in data:
        if service['email_from'] == "solutions":
            service_id = service['id']
    return service_id


def get_user_id(users, service_id):
    user_id = users[-1]['id']
    for user in users:
        if service_id in user['services']:
            user_id = user['id']
    return user_id


def get_template_id(templates, service_id):
    template_id = templates[-1]["id"]
    for template in templates:
        if template["service"] == service_id and template["template_type"] == "email":
            template_id = template["id"]
    return template_id


# def get_service_jwt(api_key_secret, service_id):
#     jwtSecret = api_key_secret
#     header = {'typ': 'JWT', 'alg': 'HS256'}
#     combo = {}
#     currentTimestamp = int(time.time())
#     data = {
#         'iss': service_id,
#         'iat': currentTimestamp,
#     }
#     combo.update(data)
#     combo.update(header)
#     encoded_jwt = jwt.encode(combo, jwtSecret, algorithm='HS256')
#     return encoded_jwt


# def create_api_key(service_id, user_id):
#     jwt = get_jwt()
#     header = {"Authorization": "Bearer " + jwt.decode("utf-8"), 'Content-Type': 'application/json'}
#     payload = json.dumps({"created_by": user_id, "key_type": "normal", "name": "userflows"})
#     r = requests.post(notification_url + "/service/" + service_id + "/api-key", headers=header, data=payload)
#     return r


# def get_api_key(service_id):
#     return get_authenticated_request("/service/" + service_id + "/api-keys")


# def get_right_api_key(get_key_response):
#     right_key = get_key_response[-1]["id"]
#     for api_key in get_key_response:
#         if api_key["name"] == "userflows" and api_key["expiry_date"] is None:
#             right_key = api_key["id"]
#     return right_key


# def revoke_key(old_key_id, service_id):
#     jwt = get_jwt()
#     header = {"Authorization": "Bearer " + jwt.decode("utf-8"), 'Content-Type': 'application/json'}
#     url = notification_url + "/service/" + service_id + "/api-key/revoke/" + old_key_id
#     r = requests.post(url, headers=header, data={})
#     return r


# def send_email(jwt, template_id):
#     header = {"Authorization": "Bearer " + jwt.decode("utf-8"), 'Content-Type': 'application/json'}
#     payload = json.dumps({"template_id": template_id, "email_address": "test@sink.govdelivery.com"})
#     r = requests.post(notification_url + "/v2/notifications/email", headers=header, data=payload)
#     return r


# def get_notification_id(notification_response):
#     return notification_response.json()['id']


# def get_notification_status(jwt, notification_id):
#     header = {"Authorization": "Bearer " + jwt.decode("utf-8"), 'Content-Type': 'application/json'}
#     r = requests.get(notification_url + "/v2/notifications/" + notification_id, headers=header)
#     return r

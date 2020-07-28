import requests
import jwt
import time
import os

staging_url = os.getenv("notification_url")
api_secret = os.getenv("NOTIFICATION_SECRET")

if(not api_secret):
    raise ValueError("Missing secret environment variable")


def get_jwt():
    jwtSecret = api_secret
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


def get_authenticated_request(endpoint):
    jwt = get_jwt()
    header = {"Authorization": "Bearer " + jwt.decode("utf-8")}
    r = requests.get(staging_url + endpoint, headers=header)
    return r


def get_status():
    r = requests.get(staging_url + "/_status")
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


def test_status():
    assert get_status().status_code == 200


def test_retrieval():
    organizations = get_organizations()
    assert organizations.status_code == 200
    services = get_services()
    assert services.status_code == 200
    service_id = get_services_id(services.json()['data'])
    users = get_users()
    assert users.status_code == 200
    templates = get_templates(service_id)
    assert templates.status_code == 200

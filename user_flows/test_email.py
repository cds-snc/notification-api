import time
import os

from steps import get_organizations
from steps import get_services
from steps import get_services_id
from steps import get_users
from steps import get_user_id
from steps import get_templates
from steps import get_template_id
from steps import get_api_key
from steps import get_right_api_key
from steps import revoke_key
from steps import create_api_key
from steps import get_service_jwt
from steps import send_email
from steps import get_notification_id
from steps import get_notification_status

notification_url = os.getenv("notification_url")
api_secret = os.getenv("NOTIFICATION_SECRET")

if(not api_secret):
    raise ValueError("Missing secret environment variable")

if(not notification_url):
    raise ValueError("Missing url")


def test_email():
    organizations = get_organizations()
    assert organizations.status_code == 200
    services = get_services()
    assert services.status_code == 200
    service_id = get_services_id(services.json()['data'])
    users = get_users()
    assert users.status_code == 200
    user_id = get_user_id(users.json()['data'], service_id)
    templates = get_templates(service_id)
    template_id = get_template_id(templates.json()['data'], service_id)
    assert templates.status_code == 200
    old_key = get_api_key(service_id)
    assert old_key.status_code == 200
    old_key_id = get_right_api_key(old_key.json()["apiKeys"])
    response = revoke_key(old_key_id, service_id)
    assert response.status_code == 202
    service_key = create_api_key(service_id, user_id)
    assert service_key.status_code == 201
    service_jwt = get_service_jwt(service_key.json()["data"], service_id)
    email_response = send_email(service_jwt, template_id)
    assert email_response.status_code == 201
    notification_id = get_notification_id(email_response)
    time_count = 0
    notification_status = ""
    while notification_status != "sending" and time_count < 30:
        notification_status_response = get_notification_status(service_jwt, notification_id)
        assert notification_status_response.status_code == 200
        notification_status = notification_status_response.json()['status']
        time.sleep(1)
        time_count = time_count + 1
    assert notification_status == 'sending'

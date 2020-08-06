import requests
import json
import jwt
import time
import os
import utils

from steps import get_organizations
from steps import get_services
from steps import get_services_id
from steps import get_users
from steps import get_templates

notification_url = os.getenv("notification_url")
api_secret = os.getenv("NOTIFICATION_SECRET")

if(not api_secret):
    raise ValueError("Missing secret environment variable")

if(not notification_url):
    raise ValueError("Missing url")


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

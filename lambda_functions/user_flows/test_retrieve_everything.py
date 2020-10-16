import boto3
import os

from steps import get_organizations
from steps import get_services
from steps import get_services_id
from steps import get_users
from steps import get_templates


client = boto3.client('ssm')


def get_secret(key):
    resp = client.get_parameter(
        Name=key,
        WithDecryption=True
    )
    return resp['Parameter']['Value']


def set_environment(environment):
    notification_url = "https://{env}.api.notifications.va.gov".format(env=environment)
    api_secret = get_secret("/{env}/notification-api/admin-client-secret".format(env=environment))

    if(not api_secret):
        raise ValueError("Could not retrieve secret environment variable")

    os.environ['notification_url'] = notification_url
    os.environ['ADMIN_CLIENT_SECRET'] = api_secret


def test_retrieval(environment):
    set_environment(environment)
    organizations = get_organizations()
    assert organizations.status_code == 200
    users = get_users()
    assert users.status_code == 200
    services = get_services()
    assert services.status_code == 200
    service_id = get_services_id(services.json()['data'])
    templates = get_templates(service_id)
    assert templates.status_code == 200

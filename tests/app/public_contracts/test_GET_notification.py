from . import validate
from app.models import EMAIL_TYPE
from app.v2.notifications.notification_schemas import get_notification_response, get_notifications_response
from tests import create_authorization_header


# v2


def test_get_v2_sms_contract(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    # Create objects
    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    notification = sample_notification(template=template, api_key=api_key)

    # Gather response
    auth_header = create_authorization_header(api_key)
    response_json = client.get(f'/v2/notifications/{notification.id}', headers=[auth_header]).get_json()

    # Validate
    validate(response_json, get_notification_response)


def test_get_v2_email_contract(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    # Create objects
    api_key = sample_api_key()
    template = sample_template(service=api_key.service, template_type=EMAIL_TYPE)
    notification = sample_notification(template=template, api_key=api_key)

    # Gather response
    auth_header = create_authorization_header(api_key)
    response_json = client.get(f'/v2/notifications/{notification.id}', headers=[auth_header]).get_json()

    # Validate
    validate(response_json, get_notification_response)


def test_get_v2_notifications_contract(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    # Create objects
    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    sample_notification(template=template, api_key=api_key)

    # Gather response
    auth_header = create_authorization_header(api_key)
    response_json = client.get('/v2/notifications', headers=[auth_header]).get_json()

    validate(response_json, get_notifications_response)

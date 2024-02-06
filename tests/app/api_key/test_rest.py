from app import DATETIME_FORMAT
from app.models import Service, EMAIL_TYPE
from datetime import datetime
import pytest


def test_get_api_key_stats_with_sends(
    notify_db_session,
    admin_request,
    sample_template,
    sample_api_key,
    sample_notification,
):
    api_key = sample_api_key()
    template = sample_template(template_type=EMAIL_TYPE)
    total_sends = 10
    for _ in range(total_sends):
        sample_notification(template=template, api_key=api_key)

    api_key_stats = admin_request.get('api_key.get_api_key_stats', api_key_id=api_key.id)['data']

    assert api_key_stats['api_key_id'] == str(api_key.id)
    assert api_key_stats['email_sends'] == total_sends
    assert api_key_stats['sms_sends'] == 0
    assert api_key_stats['total_sends'] == total_sends

    # Test that a send has occurred within the last second.
    last_send_dt = datetime.strptime(api_key_stats['last_send'], DATETIME_FORMAT)
    now = datetime.utcnow()
    time_delta = now - last_send_dt
    assert abs(time_delta.total_seconds()) < 1


def test_get_api_key_stats_no_sends(notify_db_session, admin_request, sample_api_key):
    # Add the session-scoped fixture to the function session.
    api_key = sample_api_key()
    notify_db_session.session.add(api_key)

    api_key_stats = admin_request.get('api_key.get_api_key_stats', api_key_id=api_key.id)['data']

    assert api_key_stats['api_key_id'] == str(api_key.id)
    assert api_key_stats['email_sends'] == 0
    assert api_key_stats['sms_sends'] == 0
    assert api_key_stats['total_sends'] == 0
    assert api_key_stats['last_send'] is None


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_get_api_keys_ranked(
    notify_db_session,
    admin_request,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)

    # Get the service used for that template
    service = notify_db_session.session.get(Service, template.service_id)

    # Create the two keys with the correct service
    key_0 = sample_api_key(service=service)
    key_1 = sample_api_key(service=service)

    total_sends = 10

    # Create series of notifications
    sample_notification(template=template, api_key=key_0)
    for _ in range(total_sends):
        sample_notification(template=template, api_key=key_0)
        sample_notification(template=template, api_key=key_1)

    # Collect API key usage in descending order of time created
    api_keys_ranked = admin_request.get('api_key.get_api_keys_ranked', n_days_back=2)['data']

    assert api_keys_ranked[0]['api_key_name'] == key_0.name
    assert api_keys_ranked[0]['service_name'] == service.name
    assert api_keys_ranked[0]['sms_notifications'] == 0
    assert api_keys_ranked[0]['email_notifications'] == total_sends + 1
    assert api_keys_ranked[0]['total_notifications'] == total_sends + 1
    assert 'last_notification_created' in api_keys_ranked[0]

    assert api_keys_ranked[1]['api_key_name'] == key_1.name
    assert api_keys_ranked[1]['service_name'] == service.name
    assert api_keys_ranked[1]['sms_notifications'] == 0
    assert api_keys_ranked[1]['email_notifications'] == total_sends
    assert api_keys_ranked[1]['total_notifications'] == total_sends
    assert 'last_notification_created' in api_keys_ranked[0]

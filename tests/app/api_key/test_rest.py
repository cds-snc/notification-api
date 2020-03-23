from tests.app.db import (
    create_api_key,
    create_service,
    create_notification,
    create_template
)

from tests.app.conftest import sample_notification as create_sample_notification


def test_get_api_key_stats_with_sends(admin_request, notify_db, notify_db_session):

    service = create_service(service_name='Service 1')
    api_key = create_api_key(service)
    template = create_template(service=service, template_type='email')
    # template_sms = create_template(service=service, template_type='sms')
    total_sends = 10

    for x in range(total_sends):
        # create_sample_notification(notify_db, notify_db_session, api_key=api_key, service=service)
        create_notification(template=template, api_key=api_key)

    api_key_stats = admin_request.get(
        'api_key.get_api_key_stats',
        api_key_id=api_key.id
    )['data']
    print("api_key_stats", api_key_stats)
    assert api_key_stats["api_key_id"] == str(api_key.id)
    assert api_key_stats["email_sends"] == total_sends
    assert api_key_stats["sms_sends"] == 0
    assert api_key_stats["total_sends"] == total_sends

def test_get_api_key_stats_no_sends(admin_request, notify_db, notify_db_session):

    service = create_service(service_name='Service 2')
    api_key = create_api_key(service)

    api_key_stats = admin_request.get(
        'api_key.get_api_key_stats',
        api_key_id=api_key.id
    )['data']

    assert api_key_stats["api_key_id"] == str(api_key.id)
    assert api_key_stats["email_sends"] == 0
    assert api_key_stats["sms_sends"] == 0
    assert api_key_stats["total_sends"] == 0
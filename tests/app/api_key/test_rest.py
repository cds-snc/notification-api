from datetime import datetime

from app import DATETIME_FORMAT

from tests.app.db import (
    create_api_key,
    create_service,
    create_notification,
    create_template
)


def test_get_api_key_stats_with_sends(admin_request, notify_db, notify_db_session):

    service = create_service(service_name='Service 1')
    api_key = create_api_key(service)
    template = create_template(service=service, template_type='email')
    total_sends = 10

    for x in range(total_sends):
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

    last_send_dt = datetime.strptime(api_key_stats["last_send"], DATETIME_FORMAT)
    now = datetime.utcnow()
    timedelta = now - last_send_dt
    assert abs(timedelta.total_seconds()) < 1


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
    assert api_key_stats["last_send"] is None

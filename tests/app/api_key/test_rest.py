from datetime import datetime

from app import DATETIME_FORMAT

from tests.app.db import (
    create_api_key,
    create_service,
    create_notification,
    create_template
)
from app.models import (
    KEY_TYPE_NORMAL,
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

    assert api_key_stats["api_key_id"] == str(api_key.id)
    assert api_key_stats["email_sends"] == total_sends
    assert api_key_stats["sms_sends"] == 0
    assert api_key_stats["total_sends"] == total_sends

    # the following lines test that a send has occurred within the last second
    last_send_dt = datetime.strptime(api_key_stats["last_send"], DATETIME_FORMAT)
    now = datetime.utcnow()
    time_delta = now - last_send_dt
    assert abs(time_delta.total_seconds()) < 1


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


def test_get_api_keys_ranked(admin_request, notify_db, notify_db_session):

    service = create_service(service_name='Service 1')
    api_key_1 = create_api_key(service, key_type=KEY_TYPE_NORMAL, key_name="Key 1")
    api_key_2 = create_api_key(service, key_type=KEY_TYPE_NORMAL, key_name="Key 2")
    template_email = create_template(service=service, template_type='email')
    total_sends = 10

    create_notification(template=template_email, api_key=api_key_1)
    for x in range(total_sends):
        create_notification(template=template_email, api_key=api_key_1)
        create_notification(template=template_email, api_key=api_key_2)

    api_keys_ranked = admin_request.get(
        'api_key.get_api_keys_ranked',
        n_days_back=2
    )['data']

    assert api_keys_ranked[0]["api_key_name"] == api_key_1.name
    assert api_keys_ranked[0]["service_name"] == service.name
    assert api_keys_ranked[0]["sms_notifications"] == 0
    assert api_keys_ranked[0]["email_notifications"] == total_sends + 1
    assert api_keys_ranked[0]["total_notifications"] == total_sends + 1
    assert "last_notification_created" in api_keys_ranked[0]

    assert api_keys_ranked[1]["api_key_name"] == api_key_2.name
    assert api_keys_ranked[1]["service_name"] == service.name
    assert api_keys_ranked[1]["sms_notifications"] == 0
    assert api_keys_ranked[1]["email_notifications"] == total_sends
    assert api_keys_ranked[1]["total_notifications"] == total_sends
    assert "last_notification_created" in api_keys_ranked[0]

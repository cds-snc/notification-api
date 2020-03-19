from tests.app.db import (
    create_api_key,
    create_service
)

from tests.app.conftest import sample_notification as create_sample_notification


def test_get_api_key_stats(admin_request, notify_db, notify_db_session):

    service = create_service(check_if_service_exists=True)
    api_key = create_api_key(service)

    for x in range(10):
        create_sample_notification(notify_db, notify_db_session, api_key=api_key, service=service)

    api_key_stats = admin_request.get(
        'api_key.get_api_key_stats',
        api_key_id=api_key.id
    )['data']

    assert api_key_stats["api_key_id"] == str(api_key.id)
    assert api_key_stats["total_sends"] == 10

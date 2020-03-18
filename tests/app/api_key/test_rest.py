from app.models import Notification


def test_get_api_key_stats(admin_request, notify_db, notify_db_session):
    api_key_id_1 = "api_key_id_1"
    notifications = []
    for x in range(10):
        notifications.append(Notification(api_key_id=api_key_id_1))

    notify_db.session.add_all(notifications)
    notify_db.session.commit()

    api_key_stats = admin_request.get(
        'api_key.get_api_key_stats'
    )['data']

    assert len(api_key_stats) == 1
    assert api_key_stats[0]["total_sends"] == 10

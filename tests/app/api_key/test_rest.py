from app import DATETIME_FORMAT
from app.models import EMAIL_TYPE
from datetime import datetime


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

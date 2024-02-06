from app.dao.login_event_dao import save_login_event, list_login_events
from app.models import LoginEvent


def test_save_login_event_should_create_new_login_event(notify_db_session, sample_user):
    # Create a LoginEvent that isn't persisted.
    login_event = LoginEvent(**{'user': sample_user(), 'data': {}})
    save_login_event(login_event)

    try:
        assert login_event.id is not None
        assert notify_db_session.session.get(LoginEvent, login_event.id) is not None
    finally:
        notify_db_session.session.delete(login_event)
        notify_db_session.session.commit()


def test_list_login_events(sample_user, sample_login_event):
    # Create 2 login events for the same user.
    user = sample_user()
    sample_login_event(user)
    sample_login_event(user)

    keys = list_login_events(user.id)
    assert len(keys) == 2

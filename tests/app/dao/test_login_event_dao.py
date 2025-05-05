from app.dao.login_event_dao import save_login_event
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

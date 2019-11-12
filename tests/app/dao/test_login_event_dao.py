from app.dao.login_event_dao import (
    save_login_event,
    list_login_events
)
from app.models import LoginEvent


def test_save_login_event_should_create_new_login_event(sample_user):
    login_event = LoginEvent(**{'user': sample_user, 'data': {}})

    save_login_event(login_event)
    assert LoginEvent.query.count() == 1


def test_list_login_events(sample_login_event):
    LoginEvent(**{'user': sample_login_event.user, 'data': {}})

    keys = list_login_events(sample_login_event.user.id)
    assert len(keys) == 2

from app.dao.fido2_key_dao import (
    save_fido2_key,
    list_fido2_keys,
    get_fido2_key,
    delete_fido2_key,
    create_fido2_session,
    get_fido2_session,
)
from app.models import Fido2Key, Fido2Session


def test_save_fido2_key_should_create_new_fido2_key(notify_db_session, sample_user):
    fido2_key = Fido2Key(
        **{
            'user': sample_user(),
            'name': 'Name',
            'key': 'Key',
        }
    )

    save_fido2_key(fido2_key)

    try:
        assert Fido2Key.query.count() == 1
    finally:
        # Teardown
        notify_db_session.session.delete(fido2_key)
        notify_db_session.session.commit()


def test_list_fido2_keys(sample_fido2_key):
    fido2_key = sample_fido2_key()
    sample_fido2_key(fido2_key.user)

    keys = list_fido2_keys(fido2_key.user.id)
    assert len(keys) == 2


def test_get_fido2_key(sample_fido2_key):
    fido2_key = sample_fido2_key()
    key = get_fido2_key(fido2_key.user.id, fido2_key.id)
    assert key == fido2_key


def test_delete_fido2_key(sample_fido2_key):
    fido2_key = sample_fido2_key()
    delete_fido2_key(fido2_key.user.id, fido2_key.id)
    assert Fido2Key.query.count() == 0


def test_create_fido2_session(notify_db_session, sample_user):
    create_fido2_session(sample_user().id, 'abcd')
    fido2_sessions = Fido2Session.query.all()

    try:
        assert len(fido2_sessions) == 1
    finally:
        for fido2_session in fido2_sessions:
            notify_db_session.session.delete(fido2_session)
        notify_db_session.session.commit()


def test_create_fido2_session_deletes_existing_sessions(notify_db_session, sample_user):
    user = sample_user()
    create_fido2_session(user.id, 'abcd')
    create_fido2_session(user.id, 'efgh')
    fido2_sessions = Fido2Session.query.all()

    try:
        assert Fido2Session.query.count() == 1
    finally:
        for fido2_session in fido2_sessions:
            notify_db_session.session.delete(fido2_session)
        notify_db_session.session.commit()


def test_get_fido2_key_returns_and_deletes_an_existing_session(sample_user):
    user = sample_user()
    create_fido2_session(user.id, 'abcd')
    session = get_fido2_session(user.id)
    assert Fido2Session.query.count() == 0
    assert session == 'abcd'

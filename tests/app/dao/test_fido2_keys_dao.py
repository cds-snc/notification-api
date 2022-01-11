from app.dao.fido2_key_dao import (
    save_fido2_key,
    list_fido2_keys,
    get_fido2_key,
    delete_fido2_key,
    create_fido2_session,
    get_fido2_session
)
from app.models import Fido2Key, Fido2Session


def test_save_fido2_key_should_create_new_fido2_key(sample_user):
    fido2_key = Fido2Key(**{'user': sample_user,
                            'name': "Name",
                            'key': "Key"})

    save_fido2_key(fido2_key)
    assert Fido2Key.query.count() == 1


def test_list_fido2_keys(sample_fido2_key):
    Fido2Key(**{'user': sample_fido2_key.user,
                'name': "Name",
                'key': "Key"})

    keys = list_fido2_keys(sample_fido2_key.user.id)
    assert len(keys) == 2


def test_get_fido2_key(sample_fido2_key):
    key = get_fido2_key(sample_fido2_key.user.id, sample_fido2_key.id)
    assert key == sample_fido2_key


def test_delete_fido2_key(sample_fido2_key):
    delete_fido2_key(sample_fido2_key.user.id, sample_fido2_key.id)
    assert Fido2Key.query.count() == 0


def test_create_fido2_session(sample_user):
    create_fido2_session(sample_user.id, "abcd")
    assert Fido2Session.query.count() == 1


def test_create_fido2_session_deletes_existing_sessions(sample_user):
    create_fido2_session(sample_user.id, "abcd")
    create_fido2_session(sample_user.id, "efgh")
    assert Fido2Session.query.count() == 1


def test_get_fido2_key_returns_and_deletes_an_existing_session(sample_user):
    create_fido2_session(sample_user.id, "abcd")
    session = get_fido2_session(sample_user.id)
    assert Fido2Session.query.count() == 0
    assert session == "abcd"

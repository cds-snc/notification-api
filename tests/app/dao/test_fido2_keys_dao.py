import pytest
from sqlalchemy import func, select

from app.dao.fido2_key_dao import (
    create_fido2_session,
    delete_fido2_key,
    get_fido2_key,
    get_fido2_session,
    list_fido2_keys,
    save_fido2_key,
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
    stmt = select(func.count()).select_from(Fido2Key)

    try:
        assert notify_db_session.session.scalar(stmt) == 1
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


def test_delete_fido2_key(notify_db_session, sample_fido2_key):
    fido2_key = sample_fido2_key()
    delete_fido2_key(fido2_key.user.id, fido2_key.id)

    stmt = select(func.count()).select_from(Fido2Key)
    assert notify_db_session.session.scalar(stmt) == 0


@pytest.mark.serial
def test_create_fido2_session(notify_db_session, sample_user):
    create_fido2_session(sample_user().id, 'abcd')
    stmt = select(Fido2Session)
    fido2_sessions = notify_db_session.session.scalars(stmt).all()

    try:
        assert len(fido2_sessions) == 1
    finally:
        for fido2_session in fido2_sessions:
            notify_db_session.session.delete(fido2_session)
        notify_db_session.session.commit()


@pytest.mark.serial
def test_create_fido2_session_deletes_existing_sessions(notify_db_session, sample_user):
    user = sample_user()
    create_fido2_session(user.id, 'abcd')
    create_fido2_session(user.id, 'efgh')

    stmt = select(Fido2Session)
    fido2_sessions = notify_db_session.session.scalars(stmt).all()

    try:
        assert len(fido2_sessions) == 1
    finally:
        for fido2_session in fido2_sessions:
            notify_db_session.session.delete(fido2_session)
        notify_db_session.session.commit()


def test_get_fido2_key_returns_and_deletes_an_existing_session(notify_db_session, sample_user):
    user = sample_user()
    create_fido2_session(user.id, 'abcd')
    session = get_fido2_session(user.id)

    stmt = select(func.count()).select_from(Fido2Session)
    assert notify_db_session.session.scalar(stmt) == 0
    assert session == 'abcd'

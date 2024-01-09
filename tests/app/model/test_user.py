import pytest
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError
from app.model import User
from tests.app.db import create_user


def test_can_create_user_with_idp_id():
    data = {
        'name': 'Foo Bar',
        'email_address': 'email@test.com',
        'password': 'password',
        'idp_name': 'va_sso',
        'idp_id': 'some_id',
    }
    user = User(**data)

    assert user.name == 'Foo Bar'
    assert user.email_address == 'email@test.com'
    assert user.idp_ids[0].idp_name == 'va_sso'
    assert user.idp_ids[0].idp_id == 'some_id'


def test_create_user_casts_idp_id_to_str():
    data = {
        'name': 'Foo Bar',
        'email_address': 'email@test.com',
        'password': 'password',
        'idp_name': 'va_sso',
        'idp_id': 1234,
    }
    user = User(**data)

    assert user.name == 'Foo Bar'
    assert user.email_address == 'email@test.com'
    assert user.idp_ids[0].idp_name == 'va_sso'
    assert user.idp_ids[0].idp_id == '1234'


def test_can_save_to_db(notify_db_session):
    data = {
        'name': 'Foo Bar',
        'email_address': 'email@test.com',
        'password': 'password',
        'idp_name': 'va_sso',
        'idp_id': 'some_id',
    }
    test_user = User(**data)
    test_user.save_to_db()

    loaded_user = User.query.get(test_user.id)
    assert loaded_user.name == 'Foo Bar'
    assert loaded_user.email_address == 'email@test.com'
    assert loaded_user.idp_ids[0].idp_name == 'va_sso'
    assert loaded_user.idp_ids[0].idp_id == 'some_id'


def test_can_find_by_idp_id(notify_db_session):
    data = {
        'name': 'Foo Bar',
        'email_address': 'email@test.com',
        'password': 'password',
        'idp_name': 'va_sso',
        'idp_id': 'some_id',
    }
    test_user = User(**data)
    notify_db_session.session.add(test_user)

    user = User.find_by_idp(idp_name='va_sso', idp_id='some_id')
    assert user.name == 'Foo Bar'


def test_find_by_idp_id_casts_to_str(notify_db_session):
    data = {
        'name': 'Foo Bar',
        'email_address': 'email@test.com',
        'password': 'password',
        'idp_name': 'va_sso',
        'idp_id': '1234',
    }
    test_user = User(**data)
    notify_db_session.session.add(test_user)

    user = User.find_by_idp(idp_name='va_sso', idp_id=1234)
    assert user.name == 'Foo Bar'


def test_find_by_idp_id_raises_exception_if_not_found(notify_db_session):
    data = {
        'name': 'Foo Bar',
        'email_address': 'email@test.com',
        'password': 'password',
        'idp_name': 'va_sso',
        'idp_id': 'some_id',
    }
    test_user = User(**data)
    notify_db_session.session.add(test_user)

    with pytest.raises(NoResultFound):
        User.find_by_idp(idp_name='va_sso', idp_id='some_other_id')


def test_cannot_create_users_with_same_idp_id(notify_db_session):
    test_user_1 = User(
        **{
            'name': 'Foo Bar',
            'email_address': 'test@email.com',
            'password': 'password',
            'idp_name': 'va_sso',
            'idp_id': 'some_id',
        }
    )
    test_user_1.save_to_db()

    test_user_2 = User(
        **{
            'name': 'Winnie the Pooh',
            'email_address': 'test_2@email.com',
            'password': 'other_password',
            'idp_name': 'va_sso',
            'idp_id': 'some_id',
        }
    )
    with pytest.raises(IntegrityError):
        test_user_2.save_to_db()


class TestIdentityProviders:
    def test_can_add_idp(self, notify_db_session):
        user = create_user()
        assert len(user.idp_ids) == 0

        user.add_idp(idp_name='va_sso', idp_id='some-id')
        user.save_to_db()
        assert user.idp_ids[0].idp_name == 'va_sso'
        assert user.idp_ids[0].idp_id == 'some-id'

    def test_add_idp_casts_to_str(self, notify_db_session):
        user = create_user()
        assert len(user.idp_ids) == 0

        user.add_idp(idp_name='va_sso', idp_id=1234)
        user.save_to_db()
        assert user.idp_ids[0].idp_name == 'va_sso'
        assert user.idp_ids[0].idp_id == '1234'

    def test_can_add_multiple_idps(self, notify_db_session):
        user = create_user()

        user.add_idp(idp_name='va_sso', idp_id='some-id')
        user.add_idp(idp_name='github', idp_id='some-other-id')
        user.save_to_db()
        assert len(user.idp_ids) == 2

    def test_can_not_add_multiple_ids_for_the_same_idp(self, notify_db_session):
        user = create_user()

        user.add_idp(idp_name='va_sso', idp_id='some-id')
        user.add_idp(idp_name='va_sso', idp_id='some-other-id')
        with pytest.raises(IntegrityError):
            user.save_to_db()

    def test_can_not_add_same_id_to_different_users(self, notify_db_session):
        user = create_user()
        another_user = create_user(email='email@test.com')

        user.add_idp(idp_name='va_sso', idp_id='some-id')
        user.save_to_db()

        another_user.add_idp(idp_name='va_sso', idp_id='some-id')
        with pytest.raises(IntegrityError):
            another_user.save_to_db()

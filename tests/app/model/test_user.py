import pytest
from random import randint
from uuid import uuid4

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError
from tests.app.db import transactional_save_user
from app.model import User


def test_can_create_user_with_idp_id(
    sample_user,
):
    data = {
        'name': f'{uuid4()}Foo Bar',
        'idp_name': 'va_sso',
        'idp_id': 'some_id',
    }
    user = sample_user(**data)

    assert user.name == data['name']
    assert user.idp_ids[0].idp_name == 'va_sso'
    assert user.idp_ids[0].idp_id == 'some_id'


def test_create_user_casts_idp_id_to_str(
    sample_user,
):
    data = {
        'name': f'{uuid4()}Foo Bar',
        'idp_name': 'va_sso',
        'idp_id': 1234,
    }
    user = sample_user(**data)

    assert user.name == data['name']
    assert user.idp_ids[0].idp_name == 'va_sso'
    assert user.idp_ids[0].idp_id == '1234'


def test_can_save_to_db(
    notify_db_session,
    sample_user,
):
    data = {
        'name': f'{uuid4()}Foo Bar',
        'idp_name': 'va_sso',
        'idp_id': 'some_id',
    }
    test_user = sample_user(**data)

    loaded_user = notify_db_session.session.get(User, test_user.id)

    assert loaded_user.name == data['name']
    assert loaded_user.idp_ids[0].idp_name == 'va_sso'
    assert loaded_user.idp_ids[0].idp_id == 'some_id'


def test_can_find_by_idp_id(
    sample_user,
):
    idp_id = str(uuid4())
    data = {'name': f'{uuid4()}Foo Bar', 'idp_name': 'va_sso', 'idp_id': idp_id}
    sample_user(**data)

    user = User.find_by_idp(idp_name='va_sso', idp_id=idp_id)
    assert user.name == data['name']


def test_find_by_idp_id_casts_to_str(
    sample_user,
):
    idp_id = str(randint(1, 999999999))

    data = {
        'name': f'{uuid4()}Foo Bar',
        'idp_name': 'va_sso',
        'idp_id': idp_id,
    }
    sample_user(**data)

    user = User.find_by_idp(idp_name='va_sso', idp_id=idp_id)
    assert user.name == data['name']


def test_find_by_idp_id_raises_exception_if_not_found(
    sample_user,
):
    idp_id = str(randint(1, 999999999))
    data = {'name': f'{uuid4()}Foo Bar', 'idp_name': 'va_sso', 'idp_id': idp_id}
    sample_user(**data)

    with pytest.raises(NoResultFound):
        User.find_by_idp(idp_name='va_sso', idp_id=f'{uuid4()}some_other_id')


def test_cannot_create_users_with_same_idp_id(
    sample_user,
):
    idp_id = str(randint(1, 999999999))
    sample_user(**{'name': f'{uuid4()}Foo Bar', 'idp_name': 'va_sso', 'idp_id': idp_id})

    with pytest.raises(IntegrityError):
        sample_user(**{'name': f'{uuid4()}Winnie the Pooh', 'idp_name': 'va_sso', 'idp_id': idp_id})


class TestIdentityProviders:
    def test_can_add_idp(
        self,
        sample_user,
    ):
        user = sample_user()
        assert len(user.idp_ids) == 0

        idp_id = str(randint(1, 999999999))
        user.add_idp(idp_name='va_sso', idp_id=idp_id)
        transactional_save_user(user)

        assert user.idp_ids[0].idp_name == 'va_sso'
        assert user.idp_ids[0].idp_id == idp_id

    def test_add_idp_casts_to_str(
        self,
        sample_user,
    ):
        user = sample_user()
        assert len(user.idp_ids) == 0

        idp_id = randint(1, 999999999)
        user.add_idp(idp_name='va_sso', idp_id=idp_id)
        transactional_save_user(user)

        assert user.idp_ids[0].idp_name == 'va_sso'
        assert user.idp_ids[0].idp_id == str(idp_id)

    def test_can_add_multiple_idps(
        self,
        sample_user,
    ):
        user = sample_user()
        idp_id_0 = str(randint(1, 999999999))
        idp_id_1 = str(randint(1, 999999999))

        user.add_idp(idp_name='va_sso', idp_id=idp_id_0)
        user.add_idp(idp_name='github', idp_id=idp_id_1)
        transactional_save_user(user)

        assert len(user.idp_ids) == 2

    def test_can_not_add_multiple_ids_for_the_same_idp(
        self,
        sample_user,
    ):
        user = sample_user()
        idp_id_0 = str(randint(1, 999999999))
        idp_id_1 = str(randint(1, 999999999))

        with pytest.raises(IntegrityError):
            user.add_idp(idp_name='va_sso', idp_id=idp_id_0)
            user.add_idp(idp_name='va_sso', idp_id=idp_id_1)
            transactional_save_user(user)

    def test_can_not_add_same_id_to_different_users(
        self,
        sample_user,
    ):
        user = sample_user()
        another_user = sample_user()
        idp_id = str(randint(1, 999999999))

        user.add_idp(idp_name='va_sso', idp_id=idp_id)

        with pytest.raises(IntegrityError):
            another_user.add_idp(idp_name='va_sso', idp_id=idp_id)
            transactional_save_user(another_user)

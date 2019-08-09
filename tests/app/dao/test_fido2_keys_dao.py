from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from app.dao.fido2_key_dao import (
    save_fido2_key,
    list_fido2_keys,
    get_fido2_key,
    delete_fido2_key
)
from app.models import Fido2Key


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
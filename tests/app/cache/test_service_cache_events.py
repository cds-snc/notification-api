from unittest.mock import call

from app import db
from app.cache.service_cache_events import register_service_cache_orm_events
from app.dao.service_permissions_dao import dao_add_service_permission, dao_remove_service_permission
from app.models import LETTER_TYPE
from tests.app.db import create_service


def test_service_update_invalidates_service_cache(notify_db_session, mocker):
    register_service_cache_orm_events()
    service = create_service(service_name="service-cache-update", email_from="service-cache-update")

    mocked_invalidate = mocker.patch("app.cache.service_cache_events.invalidate_service_cache_keys")

    service.name = "service-cache-update-2"
    db.session.add(service)
    db.session.commit()

    mocked_invalidate.assert_called_once_with(str(service.id))


def test_service_permission_changes_invalidate_service_cache(notify_db_session, mocker):
    register_service_cache_orm_events()
    service = create_service(service_name="service-cache-perms", email_from="service-cache-perms")

    mocked_invalidate = mocker.patch("app.cache.service_cache_events.invalidate_service_cache_keys")

    dao_add_service_permission(service.id, LETTER_TYPE)
    dao_remove_service_permission(service.id, LETTER_TYPE)

    mocked_invalidate.assert_has_calls([call(str(service.id)), call(str(service.id))])



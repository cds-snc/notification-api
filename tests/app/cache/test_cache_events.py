from unittest.mock import call

from app import db
from app.cache.cache_events import register_cache_orm_events
from app.cache.cache_invalidation_registry import CACHE_INVALIDATION_REGISTRY
from app.dao.service_permissions_dao import dao_add_service_permission, dao_remove_service_permission
from app.dao.users_dao import save_model_user
from app.models import (
    LETTER_TYPE,
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateRedacted,
    User,
)
from tests.app.db import create_service, create_template, create_user


def test_service_cache_invalidation_registry():
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[Service]] == [
        ("service", "id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[ServicePermission]] == [
        ("service", "service_id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[ServiceUser]] == [
        ("service", "service_id"),
        ("user", "user_id"),
        ("annual_limit", "service_id"),
    ]


def test_user_and_template_cache_invalidation_registry():
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[User]] == [
        ("user", "id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[Permission]] == [
        ("user", "user_id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[Template]] == [
        ("template", "id")
    ]
    assert [(rule.namespace, rule.entity_id_attribute) for rule in CACHE_INVALIDATION_REGISTRY[TemplateRedacted]] == [
        ("template", "template_id")
    ]


def test_service_update_invalidates_service_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-update", email_from="service-cache-update")

    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    service.name = "service-cache-update-2"
    db.session.add(service)
    db.session.commit()

    mocked_invalidate.assert_called_once_with("service", str(service.id))


def test_service_permission_changes_invalidate_service_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-perms", email_from="service-cache-perms")

    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    dao_add_service_permission(service.id, LETTER_TYPE)
    dao_remove_service_permission(service.id, LETTER_TYPE)

    mocked_invalidate.assert_has_calls([call("service", str(service.id)), call("service", str(service.id))])


def test_service_user_change_invalidates_service_and_user_caches(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="service-cache-user", email_from="service-cache-user")
    user = create_user()

    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    db.session.add(ServiceUser(service_id=service.id, user_id=user.id))
    db.session.commit()

    mocked_invalidate.assert_has_calls(
        [
            call("service", str(service.id)),
            call("user", str(user.id)),
            call("annual_limit", str(service.id)),
        ],
        any_order=True,
    )


def test_user_update_invalidates_user_cache(notify_db_session, mocker):
    register_cache_orm_events()
    user = create_user()
    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    save_model_user(user, update_dict={"name": "Updated name"})

    mocked_invalidate.assert_called_once_with("user", str(user.id))


def test_template_update_invalidates_template_cache(notify_db_session, mocker):
    register_cache_orm_events()
    service = create_service(service_name="template-cache-service", email_from="template-cache-service")
    template = create_template(service=service)
    mocked_invalidate = mocker.patch("app.cache.cache_events.invalidate_group_keys")

    template.name = "Updated template name"
    db.session.commit()

    mocked_invalidate.assert_called_once_with("template", str(template.id))
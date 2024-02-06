from app.dao.service_permissions_dao import dao_fetch_service_permissions, dao_remove_service_permission
from app.models import EMAIL_TYPE, SMS_TYPE, LETTER_TYPE, INTERNATIONAL_SMS_TYPE, INBOUND_SMS_TYPE


def test_create_service_permission(
    sample_service,
    sample_service_permissions,
):
    service = sample_service(service_permissions=[])
    service_permissions = sample_service_permissions(service=service, permissions=[SMS_TYPE])

    assert len(service_permissions) == 1
    assert service_permissions[0].service_id == service.id
    assert service_permissions[0].permission == SMS_TYPE


def test_fetch_service_permissions_gets_service_permissions(
    sample_service,
    sample_service_permissions,
):
    service = sample_service(service_permissions=[])
    sample_service_permissions(service=service, permissions=[LETTER_TYPE, INTERNATIONAL_SMS_TYPE, SMS_TYPE])

    service_permissions = dao_fetch_service_permissions(service.id)

    assert len(service_permissions) == 3
    assert all(sp.service_id == service.id for sp in service_permissions)
    assert all(sp.permission in [LETTER_TYPE, INTERNATIONAL_SMS_TYPE, SMS_TYPE] for sp in service_permissions)


def test_remove_service_permission(
    sample_service,
    sample_service_permissions,
):
    service = sample_service(service_permissions=[])
    sample_service_permissions(service=service, permissions=[EMAIL_TYPE, INBOUND_SMS_TYPE])

    dao_remove_service_permission(service.id, EMAIL_TYPE)

    permissions = dao_fetch_service_permissions(service.id)
    assert len(permissions) == 1
    assert permissions[0].permission == INBOUND_SMS_TYPE
    assert permissions[0].service_id == service.id

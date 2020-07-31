import uuid

from app.models import (
    ServiceSafelist,
    EMAIL_TYPE,
)

from app.dao.service_safelist_dao import (
    dao_fetch_service_safelist,
    dao_add_and_commit_safelisted_contacts,
    dao_remove_service_safelist
)

from tests.app.conftest import sample_service as create_service


def test_fetch_service_safelist_gets_safelists(sample_service_safelist):
    safelist = dao_fetch_service_safelist(sample_service_safelist.service_id)
    assert len(safelist) == 1
    assert safelist[0].id == sample_service_safelist.id


def test_fetch_service_safelist_ignores_other_service(sample_service_safelist):
    assert len(dao_fetch_service_safelist(uuid.uuid4())) == 0


def test_add_and_commit_safelisted_contacts_saves_data(sample_service):
    safelist = ServiceSafelist.from_string(sample_service.id, EMAIL_TYPE, 'foo@example.com')

    dao_add_and_commit_safelisted_contacts([safelist])

    db_contents = ServiceSafelist.query.all()
    assert len(db_contents) == 1
    assert db_contents[0].id == safelist.id


def test_remove_service_safelist_only_removes_for_my_service(notify_db, notify_db_session):
    service_1 = create_service(notify_db, notify_db_session, service_name="service 1")
    service_2 = create_service(notify_db, notify_db_session, service_name="service 2")
    dao_add_and_commit_safelisted_contacts([
        ServiceSafelist.from_string(service_1.id, EMAIL_TYPE, 'service1@example.com'),
        ServiceSafelist.from_string(service_2.id, EMAIL_TYPE, 'service2@example.com')
    ])

    dao_remove_service_safelist(service_1.id)

    assert service_1.safelist == []
    assert len(service_2.safelist) == 1


def test_remove_service_safelist_does_not_commit(notify_db, sample_service_safelist):
    dao_remove_service_safelist(sample_service_safelist.service_id)

    # since dao_remove_service_safelist doesn't commit, we can still rollback its changes
    notify_db.session.rollback()

    assert ServiceSafelist.query.count() == 1

import uuid

from app.models import (
    ServiceSafelist,
    EMAIL_TYPE,
)

from app.dao.service_whitelist_dao import (
    dao_fetch_service_safelist,
    dao_add_and_commit_safelisted_contacts,
    dao_remove_service_safelist
)

from tests.app.conftest import sample_service as create_service


def test_fetch_service_whitelist_gets_whitelists(sample_service_whitelist):
    whitelist = dao_fetch_service_safelist(sample_service_whitelist.service_id)
    assert len(whitelist) == 1
    assert whitelist[0].id == sample_service_whitelist.id


def test_fetch_service_whitelist_ignores_other_service(sample_service_whitelist):
    assert len(dao_fetch_service_safelist(uuid.uuid4())) == 0


def test_add_and_commit_whitelisted_contacts_saves_data(sample_service):
    whitelist = ServiceSafelist.from_string(sample_service.id, EMAIL_TYPE, 'foo@example.com')

    dao_add_and_commit_safelisted_contacts([whitelist])

    db_contents = ServiceSafelist.query.all()
    assert len(db_contents) == 1
    assert db_contents[0].id == whitelist.id


def test_remove_service_whitelist_only_removes_for_my_service(notify_db, notify_db_session):
    service_1 = create_service(notify_db, notify_db_session, service_name="service 1")
    service_2 = create_service(notify_db, notify_db_session, service_name="service 2")
    dao_add_and_commit_safelisted_contacts([
        ServiceSafelist.from_string(service_1.id, EMAIL_TYPE, 'service1@example.com'),
        ServiceSafelist.from_string(service_2.id, EMAIL_TYPE, 'service2@example.com')
    ])

    dao_remove_service_safelist(service_1.id)

    assert service_1.whitelist == []
    assert len(service_2.whitelist) == 1


def test_remove_service_whitelist_does_not_commit(notify_db, sample_service_whitelist):
    dao_remove_service_safelist(sample_service_whitelist.service_id)

    # since dao_remove_service_safelist doesn't commit, we can still rollback its changes
    notify_db.session.rollback()

    assert ServiceSafelist.query.count() == 1

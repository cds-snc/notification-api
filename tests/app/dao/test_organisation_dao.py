import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.dao.organisation_dao import (
    dao_add_service_to_organisation,
    dao_add_user_to_organisation,
    dao_get_invited_organisation_user,
    dao_get_organisation_by_email_address,
    dao_get_organisation_by_id,
    dao_get_organisation_by_service_id,
    dao_get_organisation_services,
    dao_get_organisations,
    dao_get_users_for_organisation,
    dao_update_organisation,
)
from app.dao.services_dao import dao_add_user_to_service, dao_create_service
from app.models import Organisation, OrganisationTypes, Service


def test_get_organisations_gets_all_organisations_alphabetically_with_active_organisations_first(sample_organisation):
    m_active_org = sample_organisation(name=f'm_active_organisation {uuid4()}')
    z_inactive_org = sample_organisation(name=f'z_inactive_organisation {uuid4()}', active=False)
    a_inactive_org = sample_organisation(name=f'a_inactive_organisation {uuid4()}', active=False)
    z_active_org = sample_organisation(name=f'z_active_organisation {uuid4()}')
    a_active_org = sample_organisation(name=f'a_active_organisation {uuid4()}')
    org_ids = frozenset((m_active_org.id, z_inactive_org.id, a_inactive_org.id, z_active_org.id, a_active_org.id))

    organisations = tuple(filter(lambda o: o.id in org_ids, dao_get_organisations()))

    assert organisations[0] == a_active_org
    assert organisations[1] == m_active_org
    assert organisations[2] == z_active_org
    assert organisations[3] == a_inactive_org
    assert organisations[4] == z_inactive_org


def test_get_organisation_by_id_gets_correct_organisation(sample_organisation):
    organisation = sample_organisation()
    organisation_from_db = dao_get_organisation_by_id(organisation.id)
    assert organisation_from_db == organisation


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_organisation(notify_db_session, sample_user, sample_organisation, sample_email_branding):
    organisation = sample_organisation()
    organisation_id = organisation.id
    email_branding = sample_email_branding()
    user = sample_user()

    data = {
        'name': 'new name',
        'crown': True,
        'organisation_type': 'other',
        'agreement_signed': True,
        'agreement_signed_at': datetime.datetime.utcnow(),
        'agreement_signed_by_id': user.id,
        'agreement_signed_version': 999.99,
        'email_branding_id': email_branding.id,
    }

    for attribute, value in data.items():
        assert getattr(organisation, attribute) != value

    assert organisation.updated_at is None

    dao_update_organisation(organisation_id, **data)

    organisation_from_db = notify_db_session.session.get(Organisation, organisation_id)
    assert organisation_from_db is not None

    for attribute, value in data.items():
        assert getattr(organisation_from_db, attribute) == value

    assert organisation_from_db.updated_at


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'domain_list, expected_domains',
    (
        (['abc', 'def'], {'abc', 'def'}),
        (['ABC', 'DEF'], {'abc', 'def'}),
        ([], set()),
        (None, {'123', '456'}),
        pytest.param(['abc', 'ABC'], {'abc'}, marks=pytest.mark.xfail(raises=IntegrityError)),
    ),
)
def test_update_organisation_domains_lowercases(
    domain_list,
    expected_domains,
    sample_organisation,
):
    organisation = sample_organisation()

    # Seed some domains
    dao_update_organisation(organisation.id, domains=['123', '456'])

    # This should overwrite the seeded domains
    dao_update_organisation(organisation.id, domains=domain_list)

    assert {domain.domain for domain in organisation.domains} == expected_domains


def test_update_organisation_does_not_update_the_service_org_type_if_org_type_is_not_provided(
    notify_db_session,
    sample_service,
    sample_organisation,
):
    service = sample_service()
    service.organisation_type = 'other'
    organisation = sample_organisation()
    organisation.organisation_type = 'other'

    organisation.services.append(service)
    notify_db_session.session.commit()

    assert organisation.name.startswith('sample organisation')

    updated_org_name = str(uuid4())
    dao_update_organisation(organisation.id, name=updated_org_name)

    assert organisation.name == updated_org_name
    assert service.organisation_type == 'other'


# @pytest.fixture(scope='function')
# def setup_org_type(notify_db_session):
#     org_type = OrganisationTypes(name='some other', annual_free_sms_fragment_limit=25000)
#     notify_db_session.session.add(org_type)
#     notify_db_session.session.commit()
#     return org_type


# @pytest.fixture
# def setup_service(
#     notify_db_session,
#     sample_user,
#     service_name='Sample service',
#     user=None,
#     restricted=False,
#     limit=1000,
#     email_from=None,
#     permissions=None,
#     research_mode=None,
# ):
#     if user is None:
#         user = sample_user()
#     if email_from is None:
#         email_from = service_name.lower().replace(' ', '.')

#     data = {
#         'name': service_name,
#         'message_limit': limit,
#         'restricted': restricted,
#         'email_from': email_from,
#         'created_by': user,
#         'crown': True,
#     }

#     stmt = select(Service).where(Service.name == service_name)
#     service = notify_db_session.session.scalars(stmt).first()

#     if not service:
#         service = Service(**data)
#         dao_create_service(service, user, service_permissions=permissions)

#         if research_mode:
#             service.research_mode = research_mode

#     else:
#         if user not in service.users:
#             dao_add_user_to_service(service, user)

#     return service


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_organisation_updates_the_service_org_type_if_org_type_is_provided(
    setup_service, sample_organisation, setup_org_type, notify_db_session
):
    setup_service.organisation_type = setup_org_type.name
    sample_organisation.organisation_type = setup_org_type.name

    sample_organisation.services.append(setup_service)
    notify_db_session.session.commit()

    dao_update_organisation(sample_organisation.id, organisation_type='other')

    assert sample_organisation.organisation_type == 'other'
    assert setup_service.organisation_type == 'other'

    history_model = Service.get_history_model()
    stmt = select(history_model).where(history_model.id == setup_service.id, history_model.version == 2)
    assert notify_db_session.session.scalars(stmt).one().organisation_type == 'other'


def test_add_service_to_organisation(notify_db_session, sample_service, sample_organisation):
    service = sample_service()
    organisation = sample_organisation()
    assert organisation.services == []

    service.organisation_type = 'other'
    organisation.organisation_type = 'other'
    organisation.crown = False

    dao_add_service_to_organisation(service, organisation.id)

    assert len(organisation.services) == 1
    assert organisation.services[0].id == service.id

    assert service.organisation_type == organisation.organisation_type
    assert service.crown == organisation.crown

    history_model = Service.get_history_model()
    stmt = select(history_model).where(history_model.id == service.id, history_model.version == 2)
    assert notify_db_session.session.scalars(stmt).one().organisation_type == organisation.organisation_type

    assert service.organisation_id == organisation.id


def test_get_organisation_services(sample_service, sample_organisation):
    service = sample_service(service_name=f'a {uuid4()}')
    organisation = sample_organisation()
    another_service = sample_service(service_name=f'b {uuid4()}')
    another_org = sample_organisation()

    dao_add_service_to_organisation(service, organisation.id)
    dao_add_service_to_organisation(another_service, organisation.id)

    org_services = dao_get_organisation_services(organisation.id)
    other_org_services = dao_get_organisation_services(another_org.id)

    assert [service.name, another_service.name] == sorted([s.name for s in org_services])
    assert not other_org_services


def test_get_organisation_by_service_id(sample_service, sample_organisation):
    service = sample_service()
    organisation = sample_organisation()
    another_service = sample_service()
    another_org = sample_organisation()

    dao_add_service_to_organisation(service, organisation.id)
    dao_add_service_to_organisation(another_service, another_org.id)

    organisation_1 = dao_get_organisation_by_service_id(service.id)
    organisation_2 = dao_get_organisation_by_service_id(another_service.id)

    assert organisation_1 == organisation
    assert organisation_2 == another_org


def test_dao_get_invited_organisation_user(sample_invited_org_user):
    invited_org_user = sample_invited_org_user()
    invited_org_user = dao_get_invited_organisation_user(invited_org_user.id)
    assert invited_org_user == invited_org_user


def test_dao_get_invited_organisation_user_returns_none(notify_api):
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_get_invited_organisation_user(uuid4())


def test_dao_get_users_for_organisation(sample_user, sample_organisation):
    first = sample_user(email='first@invited.com')
    second = sample_user(email='another@invited.com')
    organisation = sample_organisation()

    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=first.id)
    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=second.id)

    results = dao_get_users_for_organisation(organisation_id=organisation.id)

    assert len(results) == 2
    assert results[0] == first
    assert results[1] == second


def test_dao_get_users_for_organisation_returns_empty_list(sample_organisation):
    results = dao_get_users_for_organisation(organisation_id=sample_organisation().id)
    assert len(results) == 0


def test_dao_get_users_for_organisation_only_returns_active_users(sample_user, sample_organisation):
    first = sample_user()
    second = sample_user()
    organisation = sample_organisation()

    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=first.id)
    dao_add_user_to_organisation(organisation_id=organisation.id, user_id=second.id)

    second.state = 'inactive'

    results = dao_get_users_for_organisation(organisation_id=organisation.id)
    assert len(results) == 1
    assert results[0] == first


def test_add_user_to_organisation_returns_user(
    sample_organisation,
    sample_user,
):
    org_user = sample_user()
    assert not org_user.organisations
    organisation = sample_organisation()

    added_user = dao_add_user_to_organisation(organisation_id=organisation.id, user_id=org_user.id)
    assert len(added_user.organisations) == 1
    assert added_user.organisations[0] == organisation


def test_add_user_to_organisation_when_user_does_not_exist(sample_organisation):
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_add_user_to_organisation(organisation_id=sample_organisation().id, user_id=uuid4())


def test_add_user_to_organisation_when_organisation_does_not_exist(sample_user):
    with pytest.raises(expected_exception=SQLAlchemyError):
        dao_add_user_to_organisation(organisation_id=uuid4(), user_id=sample_user().id)


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'domain, expected_org',
    (
        ('unknown.gov.uk', False),
        ('example.gov.uk', True),
    ),
)
def test_get_organisation_by_email_address(
    domain,
    expected_org,
    sample_domain,
    sample_organisation,
):
    org = sample_organisation()
    sample_domain('example.gov.uk', org.id)
    sample_domain('test.gov.uk', org.id)

    another_org = sample_organisation(name='Another')
    sample_domain('cabinet-office.gov.uk', another_org.id)
    sample_domain('cabinetoffice.gov.uk', another_org.id)

    found_org = dao_get_organisation_by_email_address('test@{}'.format(domain))

    if expected_org:
        assert found_org is org
    else:
        assert found_org is None


def test_get_organisation_by_email_address_ignores_gsi_gov_uk(
    notify_db_session,
    sample_organisation,
    sample_domain,
):
    org = sample_organisation()
    domain_str = f'{str(uuid4())}example.gov.uk'
    sample_domain(domain_str, org.id)

    found_org = dao_get_organisation_by_email_address(f'test_gsi_address@{domain_str}')
    assert org == found_org

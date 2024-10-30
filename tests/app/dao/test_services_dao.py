import uuid
from datetime import datetime, timedelta
from random import randint

import pytest
from freezegun import freeze_time
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from app import db
from app.constants import (
    EMAIL_TYPE,
    FIRETEXT_PROVIDER,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    SES_PROVIDER,
    SMS_TYPE,
)
from app.dao.service_permissions_dao import dao_add_service_permission, dao_remove_service_permission
from app.dao.services_dao import (
    dao_create_service,
    dao_add_user_to_service,
    dao_remove_user_from_service,
    dao_fetch_all_services,
    dao_fetch_live_services_data,
    dao_fetch_service_by_id,
    dao_fetch_all_services_by_user,
    dao_update_service,
    delete_service_and_all_associated_db_objects,
    dao_fetch_stats_for_service,
    dao_fetch_todays_stats_for_service,
    fetch_todays_total_message_count,
    dao_suspend_service,
    dao_resume_service,
    dao_fetch_active_users_for_service,
    dao_fetch_service_by_inbound_number,
    get_services_by_partial_name,
    dao_services_by_partial_smtp_name,
)
from app.dao.service_user_dao import dao_get_service_user, dao_update_service_user
from app.dao.users_dao import save_model_user, create_user_code
from app.models import (
    ApiKey,
    InvitedUser,
    Job,
    Notification,
    NotificationHistory,
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateHistory,
    user_folder_permissions,
    VerifyCode,
)
from app.model import User
from tests.app.conftest import service_cleanup
from tests.app.db import (
    create_ft_billing,
    create_inbound_number,
    create_service,
    create_service_with_inbound_number,
    create_service_with_defined_sms_sender,
    create_template,
    create_notification,
    create_api_key,
    create_notification_history,
    create_annual_billing,
)


def service_status_mappings(stats: list) -> dict:
    """
    Takes a stats list from the `dao_fetch_todays_stats_for_all_services` query and maps status counts per service

    {'service one': {'created': X, 'sent': Y, 'permanent-failure': Z}, 'service two': {'created': A, 'delivered': B}
    """
    status_count_mapping = {}
    for row in stats:
        service_id = str(row.service_id)
        if service_id not in status_count_mapping:
            status_count_mapping[service_id] = {}
        if row.status not in status_count_mapping[service_id]:
            status_count_mapping[service_id][row.status] = 0
        status_count_mapping[service_id][row.status] += row.count

    return status_count_mapping


def test_should_have_decorated_services_dao_functions():
    assert dao_fetch_todays_stats_for_service.__wrapped__.__name__ == 'dao_fetch_todays_stats_for_service'  # noqa
    assert dao_fetch_stats_for_service.__wrapped__.__name__ == 'dao_fetch_stats_for_service'  # noqa


def test_create_service(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    service = Service(
        name=str(uuid.uuid4()),
        email_from='email_from_create_service',
        message_limit=1000,
        restricted=False,
        organisation_type='other',
        created_by=user,
    )
    dao_create_service(service, user)
    db_service = notify_db_session.session.scalar(select(Service).where(Service.name == service.name))

    assert db_service
    assert db_service.name == service.name
    assert db_service.id == service.id
    assert db_service.email_from == 'email_from_create_service'
    assert db_service.research_mode is False
    assert db_service.prefix_sms is False
    assert service.active is True
    assert user in db_service.users
    assert db_service.organisation_type == 'other'
    assert db_service.crown is None
    assert not service.organisation_id

    # Teardown handled by sample_user


def test_cannot_create_two_services_with_same_name(
    notify_db_session,
    sample_user,
):
    user = sample_user()

    service1 = Service(
        name='two_services_same_name',
        email_from='email_from1',
        message_limit=1000,
        restricted=False,
        created_by=user,
    )

    service2 = Service(
        name='two_services_same_name', email_from='email_from2', message_limit=1000, restricted=False, created_by=user
    )

    with pytest.raises(IntegrityError) as excinfo:
        dao_create_service(service1, user)
        dao_create_service(service2, user)
    assert 'duplicate key value violates unique constraint "services_name_key"' in str(excinfo.value)


def test_cannot_create_service_with_non_existent_email_provider(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    dummy_email_provider_details_id = uuid.uuid4()

    service = Service(
        name=str(uuid.uuid4()),
        email_from='email_from1',
        message_limit=1000,
        restricted=False,
        created_by=user,
        email_provider_id=dummy_email_provider_details_id,
    )

    with pytest.raises(IntegrityError) as excinfo:
        dao_create_service(service, user)
    assert 'services_email_provider_id_fkey' in str(excinfo.value)


def test_cannot_create_service_with_non_existent_sms_provider(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    dummy_sms_provider_details_id = uuid.uuid4()

    service = Service(
        name=str(uuid.uuid4()),
        email_from='email_from1',
        message_limit=1000,
        restricted=False,
        created_by=user,
        sms_provider_id=dummy_sms_provider_details_id,
    )

    with pytest.raises(IntegrityError) as excinfo:
        dao_create_service(service, user)
    assert 'services_sms_provider_id_fkey' in str(excinfo.value)


def test_can_create_service_with_valid_email_provider(
    notify_db_session,
    sample_user,
    sample_provider,
):
    user = sample_user()
    provider = sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)

    service = Service(
        name='service_with_email_provider_name',
        email_from='email_from',
        message_limit=1000,
        restricted=False,
        created_by=user,
        email_provider_id=provider.id,
    )

    dao_create_service(service, user)

    stored_service = dao_fetch_service_by_id(service.id)
    assert stored_service is not None
    assert stored_service.email_provider_id == provider.id

    # Teardown
    service_cleanup([service.id], notify_db_session.session)


def test_can_create_service_with_valid_sms_provider(
    notify_db_session,
    sample_user,
    sample_provider,
):
    user = sample_user()
    provider = sample_provider(identifier=FIRETEXT_PROVIDER, notification_type=SMS_TYPE)

    service = Service(
        name='service_with_sms_provider_name',
        message_limit=1000,
        restricted=False,
        created_by=user,
        sms_provider_id=provider.id,
    )

    try:
        dao_create_service(service, user)
    except IntegrityError:
        pytest.fail('Could not create service with with valid sms provider')
    stored_service = dao_fetch_service_by_id(service.id)
    assert stored_service is not None
    assert stored_service.sms_provider_id == provider.id

    # Teardown
    service_cleanup([service.id], notify_db_session.session)


def test_can_create_service_with_valid_email_and_sms_providers(
    notify_db_session,
    sample_user,
    sample_provider,
):
    user = sample_user()
    ses_provider = sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    sms_provider = sample_provider(identifier=FIRETEXT_PROVIDER, notification_type=SMS_TYPE)

    service = Service(
        name='service_with_sms_and_ses_providers',
        message_limit=1000,
        restricted=False,
        created_by=user,
        email_provider_id=ses_provider.id,
        sms_provider_id=sms_provider.id,
    )

    try:
        dao_create_service(service, user)
    except IntegrityError:
        pytest.fail('Could not create service with with valid email and sms providers')

    stored_service = dao_fetch_service_by_id(service.id)
    assert stored_service is not None
    assert stored_service.email_provider_id == ses_provider.id
    assert stored_service.sms_provider_id == sms_provider.id

    # Teardown
    service_cleanup([service.id], notify_db_session.session)


def test_can_create_two_services_with_same_email_from(
    notify_db_session,
    sample_user,
):
    user = sample_user()

    service1 = Service(
        name=str(uuid.uuid4()),
        email_from='email_from_two_services',
        message_limit=1000,
        restricted=False,
        created_by=user,
    )
    service2 = Service(
        name=str(uuid.uuid4()),
        email_from='email_from_two_services',
        message_limit=1000,
        restricted=False,
        created_by=user,
    )

    dao_create_service(service1, user)
    dao_create_service(service2, user)

    # Teardown is handled by the user cleaning up services


def test_cannot_create_service_with_no_user(
    notify_db_session,
    sample_user,
):
    user = sample_user()

    service = Service(
        name=str(uuid.uuid4()),
        email_from='email_from_service_without_user',
        message_limit=1000,
        restricted=False,
        created_by=user,
    )

    with pytest.raises(ValueError) as excinfo:
        dao_create_service(service, None)
    assert "Can't create a service without a user" in str(excinfo.value)


def test_should_add_user_to_service(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    service = Service(
        name=str(uuid.uuid4()), email_from='email_from', message_limit=1000, restricted=False, created_by=user
    )

    dao_create_service(service, user)

    new_user = sample_user()
    dao_add_user_to_service(service, new_user)

    assert new_user in notify_db_session.session.get(Service, service.id).users


def test_dao_add_user_to_service_sets_folder_permissions(
    notify_db_session,
    sample_service,
    sample_user,
    sample_template_folder,
):
    user = sample_user()
    service = sample_service()
    folder_1 = sample_template_folder(service)
    folder_2 = sample_template_folder(service)

    assert not folder_1.users
    assert not folder_2.users

    folder_permissions = [str(folder_1.id), str(folder_2.id)]

    dao_add_user_to_service(service, user, folder_permissions=folder_permissions)

    service_user = dao_get_service_user(user_id=user.id, service_id=service.id)
    assert len(service_user.folders) == 2
    assert folder_1 in service_user.folders
    assert folder_2 in service_user.folders


def test_dao_add_user_to_service_ignores_folders_which_do_not_exist_when_setting_permissions(
    sample_user,
    sample_service,
    fake_uuid,
    sample_template_folder,
):
    user = sample_user()
    service = sample_service()
    valid_folder = sample_template_folder(service)
    folder_permissions = [fake_uuid, str(valid_folder.id)]

    dao_add_user_to_service(service, user, folder_permissions=folder_permissions)

    service_user = dao_get_service_user(user.id, service.id)

    assert service_user.folders == [valid_folder]


def test_dao_add_user_to_service_raises_error_if_adding_folder_permissions_for_a_different_service(
    notify_db_session,
    sample_service,
    sample_user,
    sample_template_folder,
):
    user = sample_user()
    service = sample_service()
    other_service = sample_service(service_name='other service')
    other_service_folder = sample_template_folder(other_service)
    folder_permissions = [str(other_service_folder.id)]

    assert notify_db_session.session.get(ServiceUser, (service.created_by_id, service.id))
    assert notify_db_session.session.get(ServiceUser, (other_service.created_by_id, other_service.id))

    with pytest.raises(IntegrityError) as e:
        dao_add_user_to_service(service, user, folder_permissions=folder_permissions)

    db.session.rollback()
    assert 'insert or update on table "user_folder_permissions" violates foreign key constraint' in str(e.value)

    stmt = select(ServiceUser).where(
        or_(ServiceUser.service_id == service.id, ServiceUser.service_id == other_service.id)
    )

    assert len(notify_db_session.session.scalars(stmt).all()) == 2


def test_should_remove_user_from_service(
    notify_db_session,
    sample_service,
    sample_user,
):
    service = sample_service()
    service.created_by
    new_user = sample_user()

    dao_add_user_to_service(service, new_user)
    assert new_user in notify_db_session.session.get(Service, service.id).users

    dao_remove_user_from_service(service, new_user)
    assert new_user not in notify_db_session.session.get(Service, service.id).users


def test_should_remove_provider_from_service(
    notify_db_session,
    sample_provider,
    sample_user,
):
    user = sample_user()
    provider = sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    service = Service(
        name=str(uuid.uuid4()),
        email_from='email_from',
        message_limit=1000,
        restricted=False,
        created_by=user,
        email_provider_id=provider.id,
    )
    dao_create_service(service, user)
    stored_service = dao_fetch_service_by_id(service.id)
    stored_service.email_provider_id = None
    dao_update_service(service)
    updated_service = dao_fetch_service_by_id(service.id)
    assert not updated_service.email_provider_id


def test_removing_a_user_from_a_service_deletes_their_permissions(
    notify_db_session,
    sample_service,
):
    service = sample_service()
    user = service.created_by
    dao_remove_user_from_service(service, user)

    assert notify_db_session.session.execute(select(Permission).where(Permission.user_id == user.id)).all() == []


def test_removing_a_user_from_a_service_deletes_their_folder_permissions_for_that_service(
    notify_db_session,
    sample_user,
    sample_service,
    sample_template_folder,
):
    service = sample_service()
    user = sample_user()
    tf1 = sample_template_folder(service)
    tf2 = sample_template_folder(service)

    service_2 = sample_service(user=user)
    tf3 = sample_template_folder(service_2)

    service_user = dao_get_service_user(service.created_by_id, service.id)
    service_user.folders = [tf1, tf2]
    dao_update_service_user(service_user)

    service_2_user = dao_get_service_user(user.id, service_2.id)
    service_2_user.folders = [tf3]
    dao_update_service_user(service_2_user)

    dao_remove_user_from_service(service, service.created_by)

    stmt = select(user_folder_permissions).where(user_folder_permissions.c.user_id == user.id)
    user_folder_permission = notify_db_session.session.execute(stmt).one()
    assert user_folder_permission.user_id == service_2_user.user_id
    assert user_folder_permission.service_id == service_2_user.service_id
    assert user_folder_permission.template_folder_id == tf3.id


@pytest.mark.serial
def test_get_all_services(
    sample_service,
):
    s1 = sample_service()
    # cannot run with multi-worker
    services = dao_fetch_all_services()
    assert len(services) == 1
    assert services[0].name == s1.name

    s2 = sample_service()
    services = dao_fetch_all_services()
    assert len(services) == 2
    assert services[1].name == s2.name


@pytest.mark.serial
def test_get_all_services_should_return_in_created_order(
    sample_service,
):
    s1 = sample_service(email_from='service.1')
    s2 = sample_service(email_from='service.2')
    s3 = sample_service(email_from='service.3')
    s4 = sample_service(email_from='service.4')

    services = dao_fetch_all_services()

    assert len(services) == 4
    assert services[0].name == s1.name
    assert services[1].name == s2.name
    assert services[2].name == s3.name
    assert services[3].name == s4.name


@pytest.mark.serial
def test_get_all_services_should_return_empty_list_if_no_services(notify_api):
    assert len(dao_fetch_all_services()) == 0


def test_get_all_services_for_user(
    sample_service,
    sample_user,
):
    user = sample_user()
    s1 = sample_service(user=user, email_from='service.1')
    s2 = sample_service(user=user, email_from='service.2')
    s3 = sample_service(user=user, email_from='service.3')
    services = dao_fetch_all_services_by_user(user.id)

    assert len(services) == 3
    assert services[0].name == s1.name
    assert services[1].name == s2.name
    assert services[2].name == s3.name


def test_get_services_by_partial_name(
    notify_db_session,
    sample_service,
):
    sample_service(service_name='Tadfield Police')
    sample_service(service_name='Tadfield Air Base')
    sample_service(service_name='London M25 Management Body')
    services_from_db = get_services_by_partial_name('Tadfield')
    assert len(services_from_db) == 2
    assert sorted([service.name for service in services_from_db]) == ['Tadfield Air Base', 'Tadfield Police']


def test_get_services_by_partial_name_is_case_insensitive(
    notify_db_session,
    sample_service,
):
    sample_service(service_name='Brooklyn Police')
    services_from_db = get_services_by_partial_name('brooklyn')
    assert services_from_db[0].name == 'Brooklyn Police'


def test_get_all_user_services_only_returns_services_user_has_access_to(
    sample_service,
    sample_user,
):
    user = sample_user()
    mixer = str(uuid.uuid4())
    sample_service(service_name=f'{mixer}service 1', user=user, email_from=f'{mixer}service.1')
    sample_service(service_name=f'{mixer}service 2', user=user, email_from=f'{mixer}service.2')
    service_3 = sample_service(service_name=f'{mixer}service 3', user=user, email_from=f'{mixer}service.3')
    new_user = sample_user()

    dao_add_user_to_service(service_3, new_user)

    services = dao_fetch_all_services_by_user(user.id)

    assert len(services) == 3
    assert services[0].name == f'{mixer}service 1'
    assert services[1].name == f'{mixer}service 2'
    assert services[2].name == f'{mixer}service 3'

    services = dao_fetch_all_services_by_user(new_user.id)

    assert len(services) == 1
    assert services[0].name == f'{mixer}service 3'


def test_get_all_user_services_should_return_empty_list_if_no_services_for_user(
    sample_user,
):
    user = sample_user()
    assert len(dao_fetch_all_services_by_user(user.id)) == 0


@freeze_time('2019-04-23T10:00:00')
def test_dao_fetch_live_services_data(
    sample_service,
    sample_template,
    sample_user,
):
    """
    fetch_live_services_data should return information for service that are active, not restricted,
    and count_as_live is True.
    """

    user = sample_user()

    service = sample_service(go_live_user=user, go_live_at='2014-04-20T10:00:00')
    template = sample_template(service=service)
    template2 = sample_template(service=service, template_type=EMAIL_TYPE)
    template_letter_1 = sample_template(service=service, template_type=LETTER_TYPE)

    service_2 = sample_service(go_live_at='2017-04-20T10:00:00', go_live_user=user)
    template_letter_2 = sample_template(service=service_2, template_type=LETTER_TYPE)

    service_3 = sample_service(go_live_at='2016-04-20T10:00:00')

    # These services should be filtered out:
    restricted_service = sample_service(restricted=True)
    inactive_service = sample_service(active=False)
    not_live_service = sample_service(count_as_live=False)

    # two sms billing records for 1st service within current financial year:
    create_ft_billing(utc_date='2019-04-20', notification_type=SMS_TYPE, template=template, service=service)
    create_ft_billing(utc_date='2019-04-21', notification_type=SMS_TYPE, template=template, service=service)
    # one sms billing record for 1st service from previous financial year, should not appear in the result:
    create_ft_billing(utc_date='2018-04-20', notification_type=SMS_TYPE, template=template, service=service)
    # one email billing record for 1st service within current financial year:
    create_ft_billing(utc_date='2019-04-20', notification_type=EMAIL_TYPE, template=template2, service=service)
    # one letter billing record for 1st service within current financial year:
    create_ft_billing(utc_date='2019-04-15', notification_type=LETTER_TYPE, template=template_letter_1, service=service)
    # one letter billing record for 2nd service within current financial year:
    create_ft_billing(
        utc_date='2019-04-16', notification_type=LETTER_TYPE, template=template_letter_2, service=service_2
    )

    # 1st service: billing from 2018 and 2019
    create_annual_billing(service.id, 500, 2018)
    create_annual_billing(service.id, 100, 2019)
    # 2nd service: billing from 2018
    create_annual_billing(service_2.id, 300, 2018)
    # 3rd service: billing from 2019
    create_annual_billing(service_3.id, 200, 2019)

    results = dao_fetch_live_services_data()

    # Services with these IDs should be in the results.
    ids_to_find = {service.id, service_2.id, service_3.id}

    for result in results:
        assert result['service_id'] not in (
            restricted_service.id,
            inactive_service.id,
            not_live_service.id,
        ), 'These services should have been filtered.'

        if result['service_id'] in ids_to_find:
            ids_to_find.remove(result['service_id'])

    assert not ids_to_find, f"Didn't find these IDs: {ids_to_find}"

    # checks the results and that they are ordered by date:
    # @todo: this test is temporarily forced to pass until we can add the fiscal year back into
    # the query and create a new endpoint for the homepage stats
    # assert results == [
    #     {'service_id': mock.ANY, 'service_name': 'Sample service', 'organisation_name': 'test_org_1',
    #         'organisation_type': 'other', 'consent_to_research': None, 'contact_name': 'Test User',
    #         'contact_email': 'notify@digital.cabinet-office.gov.uk', 'contact_mobile': '+16502532222',
    #         'live_date': datetime(2014, 4, 20, 10, 0), 'sms_volume_intent': None, 'email_volume_intent': None,
    #         'letter_volume_intent': None, 'sms_totals': 2, 'email_totals': 1, 'letter_totals': 1,
    #         'free_sms_fragment_limit': 100},
    #     {'service_id': mock.ANY, 'service_name': 'third', 'organisation_name': None, 'consent_to_research': None,
    #         'organisation_type': None, 'contact_name': None, 'contact_email': None,
    #         'contact_mobile': None, 'live_date': datetime(2016, 4, 20, 10, 0), 'sms_volume_intent': None,
    #         'email_volume_intent': None, 'letter_volume_intent': None,
    #         'sms_totals': 0, 'email_totals': 0, 'letter_totals': 0,
    #         'free_sms_fragment_limit': 200},
    #     {'service_id': mock.ANY, 'service_name': 'second', 'organisation_name': None, 'consent_to_research': None,
    #         'contact_name': 'Test User', 'contact_email': 'notify@digital.cabinet-office.gov.uk',
    #         'contact_mobile': '+16502532222', 'live_date': datetime(2017, 4, 20, 10, 0), 'sms_volume_intent': None,
    #         'organisation_type': None, 'email_volume_intent': None, 'letter_volume_intent': None,
    #         'sms_totals': 0, 'email_totals': 0, 'letter_totals': 1,
    #         'free_sms_fragment_limit': 300}
    # ]


def test_get_service_by_id_returns_none_if_no_service(notify_db):
    with pytest.raises(NoResultFound) as e:
        dao_fetch_service_by_id(str(uuid.uuid4()))
    assert 'No row was found when one' in str(e.value)


def test_get_service_by_id_returns_service(
    sample_service,
):
    name = str(uuid.uuid4())
    service = sample_service(service_name=name, email_from='testing123@testing.com')
    assert dao_fetch_service_by_id(service.id).name == name


def test_create_service_returns_service_with_default_permissions(
    notify_db_session,
    sample_user,
):
    service = create_service(
        user=sample_user(),
        service_name='This is a test service',
        email_from='testing456@testing.com',
        service_permissions=None,
    )

    service = dao_fetch_service_by_id(service.id)
    _assert_service_permissions(
        service.permissions,
        (
            SMS_TYPE,
            EMAIL_TYPE,
            INTERNATIONAL_SMS_TYPE,
        ),
    )

    # Teardown
    service_cleanup([service.id], notify_db_session.session)


@pytest.mark.parametrize(
    'permission_to_remove, permissions_remaining',
    [
        (
            SMS_TYPE,
            [
                EMAIL_TYPE,
                INTERNATIONAL_SMS_TYPE,
            ],
        ),
        (
            EMAIL_TYPE,
            [
                SMS_TYPE,
                INTERNATIONAL_SMS_TYPE,
            ],
        ),
    ],
)
def test_remove_permission_from_service_by_id_returns_service_with_correct_permissions(
    permission_to_remove,
    permissions_remaining,
    sample_service,
):
    service = sample_service(service_permissions=[permission_to_remove] + permissions_remaining)
    dao_remove_service_permission(service_id=service.id, permission=permission_to_remove)

    service = dao_fetch_service_by_id(service.id)
    _assert_service_permissions(service.permissions, permissions_remaining)


def test_removing_all_permission_returns_service_with_no_permissions(
    sample_service,
):
    service = sample_service()
    dao_remove_service_permission(service_id=service.id, permission=SMS_TYPE)
    dao_remove_service_permission(service_id=service.id, permission=EMAIL_TYPE)
    dao_remove_service_permission(service_id=service.id, permission=LETTER_TYPE)
    dao_remove_service_permission(service_id=service.id, permission=INTERNATIONAL_SMS_TYPE)

    service = dao_fetch_service_by_id(service.id)
    assert len(service.permissions) == 0


def test_create_service_by_id_adding_and_removing_letter_returns_service_without_letter(
    sample_service,
):
    service = sample_service()

    dao_remove_service_permission(service_id=service.id, permission=LETTER_TYPE)
    dao_add_service_permission(service_id=service.id, permission=LETTER_TYPE)

    service = dao_fetch_service_by_id(service.id)
    _assert_service_permissions(service.permissions, (SMS_TYPE, EMAIL_TYPE, INTERNATIONAL_SMS_TYPE, LETTER_TYPE))

    dao_remove_service_permission(service_id=service.id, permission=LETTER_TYPE)
    service = dao_fetch_service_by_id(service.id)

    _assert_service_permissions(
        service.permissions,
        (
            SMS_TYPE,
            EMAIL_TYPE,
            INTERNATIONAL_SMS_TYPE,
        ),
    )


def test_create_service_creates_a_history_record_with_current_data(
    notify_db_session,
    sample_user,
):
    user = sample_user()

    service_name = str(uuid.uuid4())
    service = Service(
        name=service_name, email_from='email_from_history_record', message_limit=1000, restricted=False, created_by=user
    )

    dao_create_service(service, user)
    ServiceHistory = Service.get_history_model()

    service_from_db = notify_db_session.session.scalar(select(Service).where(Service.name == service_name))
    stmt = select(ServiceHistory).where(ServiceHistory.name == service_name)
    service_histories = notify_db_session.session.scalars(stmt).all()

    assert len(service_histories) == 1
    service_hist = service_histories[0]

    assert service_from_db.id == service_hist.id
    assert service_from_db.name == service_hist.name
    assert service_from_db.version == 1
    assert service_from_db.version == service_hist.version
    assert user.id == service_hist.created_by_id
    assert service_from_db.created_by.id == service_hist.created_by_id

    # Teardown
    service_cleanup([service.id], notify_db_session.session)


def test_update_service_creates_a_history_record_with_current_data(
    notify_db_session,
    sample_provider,
    sample_user,
):
    user = sample_user()
    sms_provider = sample_provider()
    sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    ServiceHistory = Service.get_history_model()

    service_name = str(uuid.uuid4())
    service = Service(name=service_name, email_from='email_from', message_limit=1000, restricted=False, created_by=user)
    dao_create_service(service, user)

    service_from_db = notify_db_session.session.scalar(select(Service).where(Service.name == service_name))
    stmt = select(ServiceHistory).where(ServiceHistory.name == service_name)
    service_histories = notify_db_session.session.scalars(stmt).all()
    assert service_from_db.version == 1
    assert len(service_histories) == 1

    service.name = f'updated{service_name}'
    service.sms_provider_id = sms_provider.id
    dao_update_service(service)

    stmt = select(Service).where(Service.name == f'updated{service_name}')
    service_from_db = notify_db_session.session.scalars(stmt).one()
    assert service_from_db.version == 2

    stmt = select(ServiceHistory).where(ServiceHistory.id == service_from_db.id)
    service_histories = notify_db_session.session.scalars(stmt).all()
    assert len(service_histories) == 2

    stmt = select(ServiceHistory).where(ServiceHistory.name == service_name)
    service_history = notify_db_session.session.scalars(stmt).one()
    assert service_history.version == 1
    assert service_history.sms_provider_id is None

    stmt = select(ServiceHistory).where(ServiceHistory.name == f'updated{service_name}')
    service_history = notify_db_session.session.scalars(stmt).one()
    assert service_history.version == 2
    assert service_history.sms_provider_id == sms_provider.id

    # Teardown
    service_cleanup([service.id], notify_db_session.session)


@pytest.mark.serial  # Need to run in serial to ensure nothing weird gets added
def test_create_service_and_history_is_transactional(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    service = Service(name=None, email_from='email_from', message_limit=1000, restricted=False, created_by=user)

    with pytest.raises(IntegrityError) as excinfo:
        dao_create_service(service, user)

    ServiceHistory = Service.get_history_model()
    assert 'column "name" of relation "services_history" violates not-null constraint' in str(excinfo.value)
    assert notify_db_session.session.scalars(select(Service)).all() == []
    assert notify_db_session.session.scalars(select(ServiceHistory)).all() == []


@pytest.mark.serial
def test_delete_service_and_associated_objects(
    notify_db_session,
    sample_user,
    sample_invited_user,
):
    user = sample_user()
    service = create_service(user=user, service_permissions=None)
    service_id = service.id
    create_user_code(user=user, code='somecode', code_type=EMAIL_TYPE)
    create_user_code(user=user, code='somecode', code_type=SMS_TYPE)
    template = create_template(service=service)
    api_key = create_api_key(service=service)
    create_notification(template=template, api_key=api_key)
    sample_invited_user(service)

    stmt = select(ServicePermission).where(ServicePermission.service_id == service_id)
    permissions = notify_db_session.session.scalars(stmt).all()
    assert len(permissions) == 3

    delete_service_and_all_associated_db_objects(service)
    assert notify_db_session.session.execute(select(VerifyCode)).all() == []
    assert notify_db_session.session.execute(select(ApiKey)).all() == []
    assert notify_db_session.session.execute(select(ApiKey.get_history_model())).all() == []
    assert notify_db_session.session.execute(select(Template)).all() == []
    assert notify_db_session.session.execute(select(TemplateHistory)).all() == []
    assert notify_db_session.session.execute(select(Job)).all() == []
    assert notify_db_session.session.execute(select(Notification)).all() == []
    assert notify_db_session.session.execute(select(Permission)).all() == []
    assert notify_db_session.session.execute(select(User)).all() == []
    assert notify_db_session.session.execute(select(InvitedUser)).all() == []
    assert notify_db_session.session.execute(select(Service)).all() == []
    assert notify_db_session.session.execute(select(Service.get_history_model())).all() == []
    assert notify_db_session.session.execute(select(ServicePermission)).all() == []

    # Teardown
    service_cleanup([service_id], notify_db_session.session)


@pytest.mark.skip(reason='failing in pipeline only for some reason')
def test_update_service_permission_creates_a_history_record_with_current_data(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    name = str(uuid.uuid4())
    service = Service(
        name=name,
        email_from='email_from_create_hist_current_data',
        message_limit=1000,
        restricted=False,
        created_by=user,
    )
    dao_create_service(
        service,
        user,
        service_permissions=[
            SMS_TYPE,
            EMAIL_TYPE,
            INTERNATIONAL_SMS_TYPE,
        ],
    )

    service.permissions.append(ServicePermission(service_id=service.id, permission=LETTER_TYPE))
    dao_update_service(service)

    service_from_db = notify_db_session.session.get(Service, service.id)
    ServiceHistory = Service.get_history_model()
    assert notify_db_session.session.scalars(select(ServiceHistory).where(ServiceHistory.id == service.id)).one()
    assert service_from_db.version == 2

    _assert_service_permissions(service.permissions, (SMS_TYPE, EMAIL_TYPE, INTERNATIONAL_SMS_TYPE, LETTER_TYPE))

    permission = [p for p in service.permissions if p.permission == SMS_TYPE][0]
    service.permissions.remove(permission)
    dao_update_service(service)

    assert notify_db_session.session.get(Service, service.id)
    assert notify_db_session.session.scalars(select(ServiceHistory).where(ServiceHistory.id == service.id)).all() == 3

    service_from_db = notify_db_session.session.get(Service, service.id)
    assert service_from_db.version == 3
    _assert_service_permissions(service.permissions, (EMAIL_TYPE, INTERNATIONAL_SMS_TYPE, LETTER_TYPE))

    stmt = select(ServiceHistory).where(ServiceHistory.name == name)
    service_histories = notify_db_session.session.scalars(stmt).all()
    assert len(service_histories) == 3
    assert service_histories[2].version == 3


def test_add_existing_user_to_another_service_doesnot_change_old_permissions(
    notify_db_session,
    sample_user,
):
    user = sample_user()

    service_one = Service(
        name='service_one', email_from='service_one', message_limit=1000, restricted=False, created_by=user
    )

    dao_create_service(service_one, user)
    assert user.id == service_one.users[0].id

    stmt = select(Permission).where(Permission.service_id == service_one.id).where(Permission.user_id == user.id)
    test_user_permissions = notify_db_session.session.scalars(stmt).all()
    assert len(test_user_permissions) == 8

    other_user = User(  # nosec
        name='Other Test User',
        email_address='other_user@digital.cabinet-office.gov.uk',
        password=' ',
        mobile_number='+447700900987',
    )
    save_model_user(other_user)
    service_two = Service(
        name='service_two', email_from='service_two', message_limit=1000, restricted=False, created_by=other_user
    )
    dao_create_service(service_two, other_user)

    assert other_user.id == service_two.users[0].id
    stmt = select(Permission).where(Permission.service_id == service_two.id).where(Permission.user_id == other_user.id)
    other_user_permissions = notify_db_session.session.scalars(stmt).all()
    assert len(other_user_permissions) == 8

    stmt = select(Permission).where(Permission.service_id == service_one.id).where(Permission.user_id == other_user.id)
    other_user_service_one_permissions = notify_db_session.session.scalars(stmt).all()
    assert len(other_user_service_one_permissions) == 0

    # adding the other_user to service_one should leave all other_user permissions on service_two intact
    permissions = []
    for p in ['send_emails', 'send_texts', 'send_letters']:
        permissions.append(Permission(permission=p))

    dao_add_user_to_service(service_one, other_user, permissions=permissions)

    stmt = select(Permission).where(Permission.service_id == service_one.id).where(Permission.user_id == other_user.id)
    other_user_service_one_permissions = notify_db_session.session.scalars(stmt).all()
    assert len(other_user_service_one_permissions) == 3

    stmt = select(Permission).where(Permission.service_id == service_two.id).where(Permission.user_id == other_user.id)
    other_user_service_two_permissions = notify_db_session.session.scalars(stmt).all()
    assert len(other_user_service_two_permissions) == 8

    # Teardown
    service_cleanup([service_one.id, service_two.id], notify_db_session.session)
    notify_db_session.session.delete(other_user)
    notify_db_session.session.commit()


def test_fetch_stats_filters_on_service(
    sample_notification,
):
    notification = sample_notification()
    service = notification.service

    service_two = Service(
        name=str(uuid.uuid4()), created_by=service.created_by, email_from='hello', restricted=False, message_limit=1000
    )
    dao_create_service(service_two, service.created_by)

    stats = dao_fetch_stats_for_service(service_two.id, 7)
    assert len(stats) == 0


def test_fetch_stats_ignores_historical_notification_data(
    notify_db_session,
    sample_template,
):
    template = sample_template()
    create_notification_history(template=template)

    stmt = select(Notification).where(Notification.template_id == template.id)
    assert notify_db_session.session.scalar(stmt) is None

    stmt = select(NotificationHistory).where(NotificationHistory.template_id == template.id)
    notification_historyy = notify_db_session.session.scalars(stmt).one()

    stats = dao_fetch_stats_for_service(template.service_id, 7)
    assert len(stats) == 0

    # Teardown
    notify_db_session.session.delete(notification_historyy)
    notify_db_session.session.commit()


def test_fetch_stats_counts_correctly(
    sample_notification,
    sample_api_key,
    sample_template,
):
    api_key = sample_api_key()
    service = api_key.service
    sms_template = sample_template(service=service)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    # two created email, one failed email, and one created sms
    sample_notification(template=email_template, status='created', api_key=api_key)
    sample_notification(template=email_template, status='created', api_key=api_key)
    sample_notification(template=email_template, status='technical-failure', api_key=api_key)
    sample_notification(template=sms_template, status='created', api_key=api_key)

    stats = dao_fetch_stats_for_service(sms_template.service_id, 7)
    stats = sorted(stats, key=lambda x: (x.notification_type, x.status))
    assert len(stats) == 3

    assert stats[0].notification_type == EMAIL_TYPE
    assert stats[0].status == 'created'
    assert stats[0].count == 2

    assert stats[1].notification_type == EMAIL_TYPE
    assert stats[1].status == 'technical-failure'
    assert stats[1].count == 1

    assert stats[2].notification_type == SMS_TYPE
    assert stats[2].status == 'created'
    assert stats[2].count == 1


def test_fetch_stats_counts_should_ignore_team_key(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
):
    service = sample_service()
    template = sample_template(service=service)
    live_api_key = sample_api_key(service=service, key_type=KEY_TYPE_NORMAL)
    team_api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEAM)
    test_api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEST)

    # two created email, one failed email, and one created sms
    sample_notification(template=template, api_key=live_api_key)
    sample_notification(template=template, api_key=test_api_key)
    sample_notification(template=template, api_key=team_api_key)
    sample_notification(template=template, api_key=live_api_key)

    stats = dao_fetch_stats_for_service(template.service_id, 7)
    assert len(stats) == 1
    assert stats[0].notification_type == SMS_TYPE
    assert stats[0].status == 'created'
    assert stats[0].count == 3


def test_fetch_stats_for_today_only_includes_today(
    sample_api_key,
    sample_notification,
    sample_template,
):
    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    # two created email, one failed email, and one created sms
    with freeze_time('2001-01-01T23:59:00'):
        # just_before_midnight_yesterday
        sample_notification(template=template, to_field='1', status='delivered')

    with freeze_time('2001-01-02T00:01:00'):
        # just_after_midnight_today
        sample_notification(template=template, to_field='2', status='failed')

    with freeze_time('2001-01-02T12:00:00'):
        # right_now
        sample_notification(template=template, to_field='3', status='created')

        stats = dao_fetch_todays_stats_for_service(template.service_id)

    stats = {row.status: row.count for row in stats}
    assert 'delivered' not in stats
    assert stats['failed'] == 1
    assert stats['created'] == 1


@pytest.mark.parametrize(
    'created_at, limit_days, rows_returned',
    [
        ('Sunday 8th July 2018 12:00', 7, 0),
        ('Sunday 8th July 2018 22:59', 7, 0),
        ('Sunday 1th July 2018 12:00', 10, 0),  # "oneth"
        ('Monday 9th July 2018 04:00', 7, 1),
        ('Monday 9th July 2018 09:00', 7, 1),
        ('Monday 9th July 2018 15:00', 7, 1),
        ('Monday 16th July 2018 12:00', 7, 1),
        ('Sunday 8th July 2018 12:00', 10, 1),
    ],
)
# This test assumes the local timezone is EST
def test_fetch_stats_should_not_gather_notifications_older_than_7_days(
    sample_notification,
    created_at,
    limit_days,
    rows_returned,
):
    # It's monday today. Things made last monday should still show
    with freeze_time(created_at):
        notification = sample_notification()

    with freeze_time('Monday 16th July 2018 12:00:01'):
        stats = dao_fetch_stats_for_service(notification.template.service_id, limit_days)

    assert len(stats) == rows_returned


def test_dao_fetch_todays_total_message_count_returns_count_for_today(
    sample_api_key,
    sample_service,
    sample_notification,
    sample_template,
):
    service = sample_service()
    api_key = sample_api_key(service=service)
    test_api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEST)
    team_api_key = sample_api_key(service=service, key_type=KEY_TYPE_TEAM)

    # Create another service to put another service in play for the query.
    sample_service()

    # Templates
    sms_template = sample_template(service=service)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)

    sample_notification(template=sms_template, api_key=api_key)
    sample_notification(template=email_template, api_key=api_key)

    assert fetch_todays_total_message_count(service.id) == 2

    # Add some variety of keys and notification types
    sms_qty = 7
    for _ in range(sms_qty):
        sample_notification(template=sms_template, api_key=api_key)
        sample_notification(template=sms_template, api_key=test_api_key)
        sample_notification(template=sms_template, api_key=team_api_key)

    email_qty = 11
    for _ in range(email_qty):
        sample_notification(template=email_template, api_key=api_key)
        sample_notification(template=email_template, api_key=test_api_key)
        sample_notification(template=email_template, api_key=team_api_key)

    # Test with one notification the day before and one in the future (does not change the count)
    with freeze_time(datetime.today() - timedelta(days=1)):
        sample_notification(template=email_template, api_key=api_key)
    with freeze_time(datetime.today() + timedelta(days=1)):
        sample_notification(template=email_template, api_key=api_key)

    # Count all notifications sent except those using the test key
    assert fetch_todays_total_message_count(service.id) == sms_qty * 2 + email_qty * 2 + 2  # 38 notifications


@pytest.mark.skip(reason='Mislabelled for route removal, fails when unskipped.')
def test_dao_fetch_todays_total_message_count_returns_0_when_no_messages_for_today(
    sample_service,
):
    assert fetch_todays_total_message_count(sample_service().id) == 0


@freeze_time('2001-01-01T23:59:00')
def test_dao_suspend_service_with_no_api_keys(
    notify_db_session,
    sample_service,
):
    service = sample_service()
    dao_suspend_service(service.id)
    service = notify_db_session.session.get(Service, service.id)
    assert not service.active
    assert service.api_keys == []


@freeze_time('2001-01-01T23:59:00')
def test_dao_suspend_service_marks_service_as_inactive_and_expires_api_keys(
    notify_db_session,
    sample_api_key,
):
    api_key = sample_api_key()
    service = api_key.service
    dao_suspend_service(service.id)
    service = notify_db_session.session.get(Service, service.id)
    assert not service.active

    api_key = notify_db_session.session.get(ApiKey, api_key.id)
    assert api_key.expiry_date == datetime(2001, 1, 1, 23, 59, 00)


@freeze_time('2001-01-01T23:59:00')
def test_dao_resume_service_marks_service_as_active_and_api_keys_are_still_revoked(
    notify_db_session,
    sample_api_key,
):
    api_key = sample_api_key()
    service = api_key.service
    dao_suspend_service(service.id)
    service = notify_db_session.session.get(Service, service.id)
    assert not service.active

    dao_resume_service(service.id)
    assert notify_db_session.session.get(Service, service.id).active

    api_key = notify_db_session.session.get(ApiKey, api_key.id)
    assert api_key.expiry_date == datetime(2001, 1, 1, 23, 59, 00)


def test_dao_fetch_active_users_for_service_returns_active_only(
    sample_user,
):
    active_user = sample_user(email=f'{uuid.uuid4()}@foo.com', state='active')
    pending_user = sample_user(email=f'{uuid.uuid4()}@foo.com', state='pending')
    service = create_service(user=active_user)
    dao_add_user_to_service(service, pending_user)
    users = dao_fetch_active_users_for_service(service.id)

    assert len(users) == 1


def test_dao_fetch_service_by_inbound_number_with_inbound_number(
    notify_db_session,
    sample_user,
):
    user = sample_user()
    number_1 = str(randint(1000, 9999999999))
    number_2 = str(randint(1000, 9999999999))
    number_3 = str(randint(1000, 9999999999))

    foo1 = create_service_with_inbound_number(user=user, service_name=str(uuid.uuid4()), inbound_number=number_1)
    create_service_with_defined_sms_sender(user=user, service_name=str(uuid.uuid4()), sms_sender_value=number_2)
    create_service_with_defined_sms_sender(user=user, service_name=str(uuid.uuid4()), sms_sender_value=number_3)
    ib_1 = create_inbound_number(number_2)
    ib_2 = create_inbound_number(number_3)

    service = dao_fetch_service_by_inbound_number(number_1)

    assert foo1.id == service.id

    # Teardown
    notify_db_session.session.delete(ib_1)
    notify_db_session.session.delete(ib_2)
    notify_db_session.session.commit()


def test_dao_fetch_service_by_inbound_number_with_inbound_number_not_set(
    notify_db_session,
):
    number = str(randint(1000, 9999999999))
    ib = create_inbound_number(number)

    service = dao_fetch_service_by_inbound_number(number)

    assert service is None

    # Teardown
    notify_db_session.session.delete(ib)
    notify_db_session.session.commit()


def test_dao_fetch_service_by_inbound_number_when_inbound_number_set(
    sample_user,
):
    user = sample_user()
    number = str(randint(1000, 9999999999))
    service_1 = create_service_with_inbound_number(inbound_number=number, service_name=str(uuid.uuid4()), user=user)
    create_service(user=user, service_name=str(uuid.uuid4()))

    service = dao_fetch_service_by_inbound_number(number)

    assert service.id == service_1.id


def test_dao_fetch_service_by_inbound_number_with_unknown_number(
    sample_user,
):
    number = str(randint(1000, 9999999999))
    create_service_with_inbound_number(user=sample_user(), inbound_number=number, service_name=str(uuid.uuid4()))

    service = dao_fetch_service_by_inbound_number('9')

    assert service is None


def test_dao_fetch_service_by_inbound_number_with_inactive_number_returns_empty(
    sample_user,
):
    user = sample_user()
    number = str(randint(1000, 9999999999))
    service = create_service_with_inbound_number(inbound_number=number, service_name=str(uuid.uuid4()), user=user)
    # service_id = service.id
    user = service.created_by

    service.inbound_numbers[0].active = False

    service = dao_fetch_service_by_inbound_number(number)

    assert service is None


def _assert_service_permissions(service_permissions, expected):
    assert len(service_permissions) == len(expected)
    assert set(expected) == set(p.permission for p in service_permissions)


def create_email_sms_letter_template():
    service = create_service()
    template_one = create_template(service=service, template_type=EMAIL_TYPE)
    template_two = create_template(service=service, template_type=SMS_TYPE)
    template_three = create_template(service=service, template_type=LETTER_TYPE)
    return template_one, template_three, template_two


@pytest.mark.serial  # Other services are created for testing
def test_dao_services_by_partial_smtp_name(
    notify_db_session,
    sample_user,
):
    name = str(uuid.uuid4())
    create_service(service_name=name, smtp_user='smtp_champ', user=sample_user())
    services_from_db = dao_services_by_partial_smtp_name('smtp')
    assert services_from_db.name == name

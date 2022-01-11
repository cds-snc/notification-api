from datetime import datetime

import pytest
from freezegun import freeze_time
from sqlalchemy import asc

from app import clients
from app.dao.provider_details_dao import (
    get_alternative_sms_provider,
    get_current_provider,
    get_provider_details_by_identifier,
    get_provider_details_by_notification_type,
    dao_switch_sms_provider_to_provider_with_identifier,
    dao_toggle_sms_provider,
    dao_update_provider_details,
    dao_get_provider_stats,
    dao_get_provider_versions,
    dao_get_sms_provider_with_equal_priority,
    get_highest_priority_active_provider_by_notification_type,
    get_active_providers_with_weights_by_notification_type
)
from app.models import ProviderDetails, ProviderDetailsHistory, ProviderRates
from app.notifications.notification_type import NotificationType
from tests.app.db import (
    create_ft_billing,
    create_service,
    create_template,
)


@pytest.fixture(scope='function')
def setup_provider_details(db_session):
    db_session.query(ProviderRates).delete()
    db_session.query(ProviderDetails).delete()

    prioritised_email_provider = ProviderDetails(**{
        'display_name': 'foo',
        'identifier': 'foo',
        'priority': 10,
        'notification_type': 'email',
        'active': True,
        'supports_international': False,
    })
    db_session.add(prioritised_email_provider)

    deprioritised_email_provider = ProviderDetails(**{
        'display_name': 'bar',
        'identifier': 'bar',
        'priority': 50,
        'notification_type': 'email',
        'active': True,
        'supports_international': False,
    })
    db_session.add(deprioritised_email_provider)

    prioritised_sms_provider = ProviderDetails(**{
        'display_name': 'some sms provider',
        'identifier': 'some_sms_provider',
        'priority': 10,
        'notification_type': 'sms',
        'active': True,
        'supports_international': False,
    })
    db_session.add(prioritised_sms_provider)

    deprioritised_sms_provider = ProviderDetails(**{
        'display_name': 'some deprioritised sms provider',
        'identifier': 'some_deprioritised_sms_provider',
        'priority': 50,
        'notification_type': 'sms',
        'active': True,
        'supports_international': False,
    })
    db_session.add(deprioritised_sms_provider)

    inactive_sms_provider = ProviderDetails(**{
        'display_name': 'some deprioritised sms provider',
        'identifier': 'some_deprioritised_sms_provider',
        'priority': 20,
        'notification_type': 'sms',
        'active': False,
        'supports_international': False,
    })
    db_session.add(inactive_sms_provider)

    db_session.commit()

    return [
        prioritised_email_provider,
        deprioritised_email_provider,
        prioritised_sms_provider,
        deprioritised_sms_provider,
        inactive_sms_provider
    ]


@pytest.fixture(scope='function')
def setup_sms_providers(db_session):
    db_session.query(ProviderRates).delete()
    db_session.query(ProviderDetails).delete()
    db_session.query(ProviderDetailsHistory).delete()

    providers = [
        ProviderDetails(**{
            'display_name': 'foo',
            'identifier': 'foo',
            'priority': 10,
            'notification_type': 'sms',
            'active': False,
            'supports_international': False,
        }),
        ProviderDetails(**{
            'display_name': 'bar',
            'identifier': 'bar',
            'priority': 20,
            'notification_type': 'sms',
            'active': True,
            'supports_international': False,
        }),
        ProviderDetails(**{
            'display_name': 'baz',
            'identifier': 'baz',
            'priority': 30,
            'notification_type': 'sms',
            'active': True,
            'supports_international': False,
        })
    ]
    db_session.add_all(providers)
    return providers


@pytest.fixture(scope='function')
def setup_sms_providers_with_history(db_session, setup_sms_providers):
    db_session.query(ProviderDetailsHistory).delete()
    providers_history = [ProviderDetailsHistory.from_original(provider) for provider in setup_sms_providers]
    db_session.add_all(providers_history)
    return setup_sms_providers


@pytest.fixture(scope='function')
def setup_equal_priority_sms_providers(db_session):
    db_session.query(ProviderRates).delete()
    db_session.query(ProviderDetails).delete()

    providers = [
        ProviderDetails(**{
            'display_name': 'bar',
            'identifier': 'bar',
            'priority': 20,
            'notification_type': 'sms',
            'active': True,
            'supports_international': False,
        }),
        ProviderDetails(**{
            'display_name': 'baz',
            'identifier': 'baz',
            'priority': 20,
            'notification_type': 'sms',
            'active': True,
            'supports_international': False,
        })
    ]
    db_session.add_all(providers)
    return providers


def set_primary_sms_provider(identifier):
    primary_provider = get_provider_details_by_identifier(identifier)
    secondary_provider = get_alternative_sms_provider(identifier)

    primary_provider.priority = 10
    secondary_provider.priority = 20

    dao_update_provider_details(primary_provider)
    dao_update_provider_details(secondary_provider)


def test_can_get_sms_all_providers(restore_provider_details):
    sms_providers = get_provider_details_by_notification_type('sms')
    assert len(sms_providers) == 6
    assert all('sms' == prov.notification_type for prov in sms_providers)


def test_can_get_sms_international_providers(restore_provider_details):
    sms_providers = get_provider_details_by_notification_type('sms', True)
    assert len(sms_providers) == 1
    assert all('sms' == prov.notification_type for prov in sms_providers)
    assert all(prov.supports_international for prov in sms_providers)


def test_can_get_sms_providers_in_order_of_priority(restore_provider_details):
    providers = get_provider_details_by_notification_type('sms', False)

    assert providers[0].priority < providers[1].priority


def test_can_get_email_providers_in_order_of_priority(setup_provider_details):
    providers = get_provider_details_by_notification_type('email')
    [prioritised_email_provider, deprioritised_email_provider, _, _, _] = setup_provider_details
    assert providers[0].identifier == prioritised_email_provider.identifier
    assert providers[1].identifier == deprioritised_email_provider.identifier


def test_can_get_email_providers(setup_provider_details):
    email_providers = [provider for provider in setup_provider_details if provider.notification_type == 'email']
    assert len(get_provider_details_by_notification_type('email')) == len(email_providers)
    types = [provider.notification_type for provider in get_provider_details_by_notification_type('email')]
    assert all('email' == notification_type for notification_type in types)


def commit_to_db(db_session, *providers):
    db_session.query(ProviderRates).delete()
    db_session.query(ProviderDetails).delete()

    for provider in providers:
        db_session.add(provider)

    db_session.commit()


class TestGetHighestPriorityActiveProviderByNotificationType:

    default_type = NotificationType.EMAIL

    @staticmethod
    def provider_factory(
            priority: int = 10,
            notification_type: NotificationType = default_type,
            active: bool = True,
            supports_international: bool = True
    ) -> ProviderDetails:
        return ProviderDetails(**{
            'display_name': 'foo',
            'identifier': 'foo',
            'priority': priority,
            'notification_type': notification_type.value,
            'active': active,
            'supports_international': supports_international,
        })

    def test_gets_matching_type(self, db_session):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)
        sms_provider = self.provider_factory(notification_type=NotificationType.SMS)

        commit_to_db(db_session, email_provider, sms_provider)

        assert get_highest_priority_active_provider_by_notification_type(NotificationType.EMAIL) == email_provider

        assert get_highest_priority_active_provider_by_notification_type(NotificationType.SMS) == sms_provider

    def test_gets_higher_priority(self, db_session):
        low_number_priority_provider = self.provider_factory(priority=10)
        high_number_priority_provider = self.provider_factory(priority=50)

        commit_to_db(db_session, low_number_priority_provider, high_number_priority_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(self.default_type)
        assert actual_provider == low_number_priority_provider

    def test_gets_active(self, db_session):
        active_provider = self.provider_factory(active=True)
        inactive_provider = self.provider_factory(active=False)

        commit_to_db(db_session, active_provider, inactive_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(self.default_type)
        assert actual_provider == active_provider

    def test_gets_international(self, db_session):
        international_provider = self.provider_factory(supports_international=True)
        non_international_provider = self.provider_factory(supports_international=False)

        commit_to_db(db_session, international_provider, non_international_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(self.default_type, True)
        assert actual_provider == international_provider

    def test_returns_none(self, db_session):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)

        commit_to_db(db_session, email_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(NotificationType.SMS, True)
        assert actual_provider is None


class TestGetActiveProvidersWithWeightsByNotificationType:

    default_type = NotificationType.EMAIL

    @staticmethod
    def provider_factory(
            load_balancing_weight: int = 10,
            notification_type: NotificationType = default_type,
            active: bool = True,
            supports_international: bool = True
    ) -> ProviderDetails:
        return ProviderDetails(**{
            'display_name': 'foo',
            'identifier': 'foo',
            'priority': 10,
            'load_balancing_weight': load_balancing_weight,
            'notification_type': notification_type.value,
            'active': active,
            'supports_international': supports_international,
        })

    def test_gets_matching_type(self, db_session):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)
        sms_provider = self.provider_factory(notification_type=NotificationType.SMS)

        commit_to_db(db_session, email_provider, sms_provider)

        assert get_active_providers_with_weights_by_notification_type(NotificationType.EMAIL) == [email_provider]

        assert get_active_providers_with_weights_by_notification_type(NotificationType.SMS) == [sms_provider]

    def test_gets_weighted(self, db_session):
        weighted_provider = self.provider_factory(load_balancing_weight=10)
        unweighted_provider = self.provider_factory()
        unweighted_provider.load_balancing_weight = None

        commit_to_db(db_session, weighted_provider, unweighted_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(self.default_type)
        assert actual_providers == [weighted_provider]

    def test_gets_active(self, db_session):
        active_provider = self.provider_factory(active=True)
        inactive_provider = self.provider_factory(active=False)

        commit_to_db(db_session, active_provider, inactive_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(self.default_type)
        assert actual_providers == [active_provider]

    def test_gets_international(self, db_session):
        international_provider = self.provider_factory(supports_international=True)
        non_international_provider = self.provider_factory(supports_international=False)

        commit_to_db(db_session, international_provider, non_international_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(self.default_type, True)
        assert actual_providers == [international_provider]

    def test_returns_empty_list(self, db_session):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)

        commit_to_db(db_session, email_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(NotificationType.SMS)
        assert actual_providers == []


def test_should_not_error_if_any_provider_in_code_not_in_database(restore_provider_details):
    ProviderDetails.query.filter_by(identifier='sns').delete()

    assert clients.get_sms_client('sns')


@freeze_time('2000-01-01T00:00:00')
def test_update_adds_history(restore_provider_details):
    ses = ProviderDetails.query.filter(ProviderDetails.identifier == 'ses').one()
    ses_history = ProviderDetailsHistory.query.filter(ProviderDetailsHistory.id == ses.id).one()

    assert ses.version == 1
    assert ses_history.version == 1
    assert ses.updated_at is None

    ses.active = False

    dao_update_provider_details(ses)

    assert not ses.active
    assert ses.updated_at == datetime(2000, 1, 1, 0, 0, 0)

    ses_history = ProviderDetailsHistory.query.filter(
        ProviderDetailsHistory.id == ses.id
    ).order_by(
        ProviderDetailsHistory.version
    ).all()

    assert ses_history[0].active
    assert ses_history[0].version == 1
    assert ses_history[0].updated_at is None

    assert not ses_history[1].active
    assert ses_history[1].version == 2
    assert ses_history[1].updated_at == datetime(2000, 1, 1, 0, 0, 0)


def test_update_sms_provider_to_inactive_sets_inactive(restore_provider_details):
    set_primary_sms_provider('sns')
    primary_provider = get_current_provider('sms')
    primary_provider.active = False

    dao_update_provider_details(primary_provider)

    assert not primary_provider.active


def test_get_current_sms_provider_returns_provider_highest_priority_active_provider(setup_sms_providers):
    provider = get_current_provider('sms')
    assert provider.identifier == setup_sms_providers[1].identifier


def test_get_alternative_sms_provider_returns_next_highest_priority_active_sms_provider(setup_provider_details):
    active_sms_providers = [
        provider for provider in setup_provider_details
        if provider.notification_type == 'sms' and provider.active
    ]

    for provider in active_sms_providers:
        alternative_provider = get_alternative_sms_provider(provider.identifier)

        assert alternative_provider.identifier != provider.identifier
        assert alternative_provider.active


def test_switch_sms_provider_to_current_provider_does_not_switch(
    restore_provider_details,
    current_sms_provider
):
    dao_switch_sms_provider_to_provider_with_identifier(current_sms_provider.identifier)
    new_provider = get_current_provider('sms')

    assert current_sms_provider.id == new_provider.id
    assert current_sms_provider.identifier == new_provider.identifier


def test_switch_sms_provider_to_inactive_provider_does_not_switch(setup_sms_providers):
    [inactive_provider, current_provider, _] = setup_sms_providers
    assert get_current_provider('sms').identifier == current_provider.identifier

    dao_switch_sms_provider_to_provider_with_identifier(inactive_provider.identifier)
    new_provider = get_current_provider('sms')

    assert new_provider.id == current_provider.id
    assert new_provider.identifier == current_provider.identifier


def test_toggle_sms_provider_should_not_switch_provider_if_no_alternate_provider(mocker):
    mocker.patch(
        'app.dao.provider_details_dao.get_alternative_sms_provider',
        return_value=None
    )
    mock_dao_switch_sms_provider_to_provider_with_identifier = mocker.patch(
        'app.dao.provider_details_dao.dao_switch_sms_provider_to_provider_with_identifier'
    )
    dao_toggle_sms_provider('some-identifier')

    mock_dao_switch_sms_provider_to_provider_with_identifier.assert_not_called()


def test_toggle_sms_provider_switches_provider(
    mocker,
    sample_user,
    setup_sms_providers
):
    [inactive_provider, old_provider, alternative_provider] = setup_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)
    dao_toggle_sms_provider(old_provider.identifier)
    new_provider = get_current_provider('sms')

    assert new_provider.identifier != old_provider.identifier
    assert new_provider.priority < old_provider.priority


def test_toggle_sms_provider_switches_when_provider_priorities_are_equal(
    mocker,
    sample_user,
    setup_equal_priority_sms_providers
):
    [old_provider, alternative_provider] = setup_equal_priority_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    dao_toggle_sms_provider(old_provider.identifier)
    new_provider = get_current_provider('sms')

    assert new_provider.identifier != old_provider.identifier
    assert new_provider.priority < old_provider.priority
    assert old_provider.priority == new_provider.priority + 10


def test_toggle_sms_provider_updates_provider_history(
    mocker,
    sample_user,
    setup_sms_providers_with_history
):
    [inactive_provider, current_provider, alternative_provider] = setup_sms_providers_with_history
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    current_provider_history = dao_get_provider_versions(current_provider.id)

    dao_toggle_sms_provider(current_provider.identifier)

    updated_provider_history_rows = dao_get_provider_versions(current_provider.id)

    assert len(updated_provider_history_rows) - len(current_provider_history) == 1
    assert updated_provider_history_rows[0].version - current_provider_history[0].version == 1


def test_toggle_sms_provider_switches_provider_stores_notify_user_id(
    mocker,
    sample_user,
    setup_sms_providers
):
    [inactive_provider, current_provider, alternative_provider] = setup_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    dao_toggle_sms_provider(current_provider.identifier)
    new_provider = get_current_provider('sms')

    assert current_provider.identifier != new_provider.identifier
    assert new_provider.created_by.id == sample_user.id
    assert new_provider.created_by_id == sample_user.id


def test_toggle_sms_provider_switches_provider_stores_notify_user_id_in_history(
    mocker,
    sample_user,
    setup_sms_providers_with_history
):
    [inactive_provider, old_provider, alternative_provider] = setup_sms_providers_with_history
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    dao_toggle_sms_provider(old_provider.identifier)
    new_provider = get_current_provider('sms')

    old_provider_from_history = ProviderDetailsHistory.query.filter_by(
        identifier=old_provider.identifier,
        version=old_provider.version
    ).order_by(
        asc(ProviderDetailsHistory.priority)
    ).first()
    new_provider_from_history = ProviderDetailsHistory.query.filter_by(
        identifier=new_provider.identifier,
        version=new_provider.version
    ).order_by(
        asc(ProviderDetailsHistory.priority)
    ).first()

    assert old_provider.version == old_provider_from_history.version
    assert new_provider.version == new_provider_from_history.version
    assert new_provider_from_history.created_by_id == sample_user.id
    assert old_provider_from_history.created_by_id == sample_user.id


def test_can_get_all_provider_history_with_newest_first(setup_sms_providers_with_history):
    [inactive_provider, current_provider, alternative_provider] = setup_sms_providers_with_history
    current_provider.priority += 1
    dao_update_provider_details(current_provider)
    versions = dao_get_provider_versions(current_provider.id)
    assert len(versions) == 2
    assert versions[0].version == 2


def test_get_sms_provider_with_equal_priority_returns_provider(
    setup_equal_priority_sms_providers
):
    [current_provider, alternative_provider] = setup_equal_priority_sms_providers

    conflicting_provider = \
        dao_get_sms_provider_with_equal_priority(current_provider.identifier, current_provider.priority)

    assert conflicting_provider.identifier == alternative_provider.identifier


def test_get_current_sms_provider_returns_active_only(restore_provider_details):
    current_provider = get_current_provider('sms')
    current_provider.active = False
    dao_update_provider_details(current_provider)
    new_current_provider = get_current_provider('sms')

    assert current_provider.identifier != new_current_provider.identifier


def test_dao_get_provider_stats_returns_data_in_type_and_identifier_order(setup_provider_details):
    all_provider_details = setup_provider_details
    result = dao_get_provider_stats()
    assert len(result) == len(all_provider_details)

    [prioritised_email_provider, deprioritised_email_provider, prioritised_sms_provider, _, _] = setup_provider_details

    assert result[0].identifier == prioritised_email_provider.identifier
    assert result[0].display_name == prioritised_email_provider.display_name

    assert result[1].identifier == deprioritised_email_provider.identifier
    assert result[1].display_name == deprioritised_email_provider.display_name

    assert result[2].identifier == prioritised_sms_provider.identifier
    assert result[2].display_name == prioritised_sms_provider.display_name


@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_ignores_billable_sms_older_than_1_month(setup_provider_details):
    sms_provider = next((provider for provider in setup_provider_details if provider.notification_type == 'sms'), None)

    service = create_service(service_name='1')
    sms_template = create_template(service, 'sms')

    create_ft_billing('2017-06-05', 'sms', sms_template, service, provider=sms_provider.identifier, billable_unit=4)

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 0


@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_counts_billable_sms_within_last_month(setup_provider_details):
    sms_provider = next((provider for provider in setup_provider_details if provider.notification_type == 'sms'), None)

    service = create_service(service_name='1')
    sms_template = create_template(service, 'sms')

    create_ft_billing('2018-06-05', 'sms', sms_template, service, provider=sms_provider.identifier, billable_unit=4)

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 4


@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_counts_billable_sms_within_last_month_with_rate_multiplier(setup_provider_details):
    sms_provider = next((provider for provider in setup_provider_details if provider.notification_type == 'sms'), None)

    service = create_service(service_name='1')
    sms_template = create_template(service, 'sms')

    create_ft_billing(
        '2018-06-05',
        'sms',
        sms_template,
        service,
        provider=sms_provider.identifier,
        billable_unit=4,
        rate_multiplier=2
    )

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 8

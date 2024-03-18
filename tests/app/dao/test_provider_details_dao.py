from datetime import datetime
from typing import List
from uuid import uuid4

import pytest
from freezegun import freeze_time
from sqlalchemy import delete, desc, select

from app import clients
from app.dao.provider_details_dao import (
    dao_get_provider_stats,
    dao_get_provider_versions,
    dao_get_sms_provider_with_equal_priority,
    dao_switch_sms_provider_to_provider_with_identifier,
    dao_toggle_sms_provider,
    dao_update_provider_details,
    get_active_providers_with_weights_by_notification_type,
    get_alternative_sms_provider,
    get_current_provider,
    get_highest_priority_active_provider_by_notification_type,
    get_provider_details_by_identifier,
    get_provider_details_by_notification_type,
)
from app.models import (
    EMAIL_TYPE,
    PINPOINT_PROVIDER,
    SES_PROVIDER,
    SMS_TYPE,
    SNS_PROVIDER,
    ProviderDetails,
    ProviderDetailsHistory,
    ProviderRates,
)
from app.notifications.notification_type import NotificationType


@pytest.fixture
def setup_provider_details(sample_provider) -> List[ProviderDetails]:
    prioritised_email_provider = sample_provider(
        identifier=uuid4(),
        display_name='foo',
        priority=10,
        notification_type=EMAIL_TYPE,
    )

    deprioritised_email_provider = sample_provider(
        identifier=uuid4(),
        display_name='bar',
        priority=50,
        notification_type=EMAIL_TYPE,
    )

    prioritised_sms_provider = sample_provider(
        identifier=uuid4(),
        display_name='some sms provider',
        priority=10,
        notification_type=SMS_TYPE,
    )

    deprioritised_sms_provider = sample_provider(
        identifier=uuid4(),
        display_name='some deprioritised sms provider',
        priority=50,
        notification_type=SMS_TYPE,
    )

    inactive_sms_provider = sample_provider(
        identifier=uuid4(),
        display_name='some_deprioritised_sms_provider',
        priority=20,
        notification_type=SMS_TYPE,
        active=False,
    )

    return [
        prioritised_email_provider,
        deprioritised_email_provider,
        prioritised_sms_provider,
        deprioritised_sms_provider,
        inactive_sms_provider,
    ]


@pytest.fixture
def setup_sms_providers(sample_provider):
    identifier = str(uuid4())

    return [
        sample_provider(
            identifier=f'foo {identifier}',
            display_name='foo',
            priority=10,
            notification_type=SMS_TYPE,
            active=False,
        ),
        sample_provider(
            identifier=f'bar {identifier}',
            display_name='bar',
            priority=20,
            notification_type=SMS_TYPE,
        ),
        sample_provider(
            identifier=f'baz {identifier}',
            display_name='baz',
            priority=30,
            notification_type=SMS_TYPE,
        ),
    ]


@pytest.fixture
def setup_equal_priority_sms_providers(restore_provider_details):
    """
    restore_provider_details is an alias for notify_db_session that provides additional behaviors.
    """

    stmt = delete(ProviderRates)
    restore_provider_details.session.execute(stmt)

    stmt = delete(ProviderDetails)
    restore_provider_details.session.execute(stmt)

    providers = [
        ProviderDetails(
            **{
                'display_name': 'bar',
                'identifier': 'bar',
                'priority': 20,
                'notification_type': SMS_TYPE,
                'active': True,
                'supports_international': False,
            }
        ),
        ProviderDetails(
            **{
                'display_name': 'baz',
                'identifier': 'baz',
                'priority': 20,
                'notification_type': SMS_TYPE,
                'active': True,
                'supports_international': False,
            }
        ),
    ]
    restore_provider_details.session.add_all(providers)
    restore_provider_details.session.commit()
    return providers


@pytest.mark.skip(reason="#1436 - This test doesn't have proper teardown.")
def set_primary_sms_provider(identifier):
    primary_provider = get_provider_details_by_identifier(identifier)
    secondary_provider = get_alternative_sms_provider(identifier)

    primary_provider.priority = 10
    secondary_provider.priority = 20

    dao_update_provider_details(primary_provider)
    dao_update_provider_details(secondary_provider)


@pytest.mark.serial
@pytest.mark.parametrize(
    'notification_type, alternate',
    [
        (SMS_TYPE, EMAIL_TYPE),
        (EMAIL_TYPE, SMS_TYPE),
    ],
)
def test_get_provider_details_by_notification_type(
    sample_provider,
    notification_type,
    alternate,
):
    provider1 = sample_provider(notification_type=notification_type)
    provider2 = sample_provider(notification_type=notification_type, active=False)
    provider3 = sample_provider(notification_type=alternate)
    provider4 = sample_provider(notification_type=alternate, active=False)

    providers = get_provider_details_by_notification_type(notification_type, False)

    assert all(prov.notification_type == notification_type for prov in providers)
    assert provider1 in providers
    assert provider2 in providers
    assert provider3 not in providers
    assert provider4 not in providers


def test_can_get_sms_international_providers(sample_provider):
    provider = sample_provider(supports_international=True)
    assert provider.notification_type == SMS_TYPE

    sms_providers = get_provider_details_by_notification_type(SMS_TYPE, True)
    assert provider in sms_providers


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_can_get_sms_providers_in_order_of_priority(restore_provider_details, sample_provider):
    provider1 = sample_provider(priority=10)
    provider2 = sample_provider(priority=11)

    providers = get_provider_details_by_notification_type(SMS_TYPE, False)
    assert providers[0].id == provider1.id
    assert providers[1].id == provider2.id


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_can_get_email_providers_in_order_of_priority(setup_provider_details):
    [prioritised_email_provider, deprioritised_email_provider, _, _, _] = setup_provider_details
    providers = get_provider_details_by_notification_type(EMAIL_TYPE)

    assert providers[0].id == prioritised_email_provider.id
    assert providers[0].identifier == prioritised_email_provider.identifier
    assert providers[1].id == deprioritised_email_provider.id
    assert providers[1].identifier == deprioritised_email_provider.identifier


@pytest.mark.skip(reason="#1436 - This test doesn't have proper teardown.")
@pytest.mark.serial
def test_can_get_email_providers(setup_provider_details):
    email_providers = [provider for provider in setup_provider_details if provider.notification_type == EMAIL_TYPE]
    providers = get_provider_details_by_notification_type(EMAIL_TYPE)

    for p in email_providers:
        assert p.notification_type == EMAIL_TYPE
        assert p in providers


def commit_to_db(restore_provider_details, *providers):
    stmt = delete(ProviderRates)
    restore_provider_details.session.execute(stmt)

    stmt = delete(ProviderDetails)
    restore_provider_details.session.execute(stmt)

    for provider in providers:
        restore_provider_details.session.add(provider)

    restore_provider_details.session.commit()


@pytest.mark.serial
class TestGetHighestPriorityActiveProviderByNotificationType:
    default_type = NotificationType.EMAIL

    @staticmethod
    def provider_factory(
        priority: int = 10,
        notification_type: NotificationType = default_type,
        active: bool = True,
        supports_international: bool = True,
    ) -> ProviderDetails:
        return ProviderDetails(
            **{
                'display_name': 'foo',
                'identifier': 'foo',
                'priority': priority,
                'notification_type': notification_type.value,
                'active': active,
                'supports_international': supports_international,
            }
        )

    def test_gets_matching_type(self, restore_provider_details):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)
        sms_provider = self.provider_factory(notification_type=NotificationType.SMS)

        commit_to_db(restore_provider_details, email_provider, sms_provider)

        assert get_highest_priority_active_provider_by_notification_type(NotificationType.EMAIL) == email_provider

        assert get_highest_priority_active_provider_by_notification_type(NotificationType.SMS) == sms_provider

    def test_gets_higher_priority(self, restore_provider_details):
        low_number_priority_provider = self.provider_factory(priority=10)
        high_number_priority_provider = self.provider_factory(priority=50)

        commit_to_db(restore_provider_details, low_number_priority_provider, high_number_priority_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(self.default_type)
        assert actual_provider == low_number_priority_provider

    def test_gets_active(self, restore_provider_details):
        active_provider = self.provider_factory(active=True)
        inactive_provider = self.provider_factory(active=False)

        commit_to_db(restore_provider_details, active_provider, inactive_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(self.default_type)
        assert actual_provider == active_provider

    def test_gets_international(self, restore_provider_details):
        international_provider = self.provider_factory(supports_international=True)
        non_international_provider = self.provider_factory(supports_international=False)

        commit_to_db(restore_provider_details, international_provider, non_international_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(self.default_type, True)
        assert actual_provider == international_provider

    def test_returns_none(self, restore_provider_details):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)

        commit_to_db(restore_provider_details, email_provider)

        actual_provider = get_highest_priority_active_provider_by_notification_type(NotificationType.SMS, True)
        assert actual_provider is None


@pytest.mark.serial
class TestGetActiveProvidersWithWeightsByNotificationType:
    default_type = NotificationType.EMAIL

    @staticmethod
    def provider_factory(
        load_balancing_weight: int = 10,
        notification_type: NotificationType = default_type,
        active: bool = True,
        supports_international: bool = True,
    ) -> ProviderDetails:
        return ProviderDetails(
            **{
                'display_name': 'foo',
                'identifier': 'foo',
                'priority': 10,
                'load_balancing_weight': load_balancing_weight,
                'notification_type': notification_type.value,
                'active': active,
                'supports_international': supports_international,
            }
        )

    def test_gets_matching_type(self, restore_provider_details):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)
        sms_provider = self.provider_factory(notification_type=NotificationType.SMS)

        commit_to_db(restore_provider_details, email_provider, sms_provider)

        assert get_active_providers_with_weights_by_notification_type(NotificationType.EMAIL) == [email_provider]

        assert get_active_providers_with_weights_by_notification_type(NotificationType.SMS) == [sms_provider]

    def test_gets_weighted(self, restore_provider_details):
        weighted_provider = self.provider_factory(load_balancing_weight=10)
        unweighted_provider = self.provider_factory()
        unweighted_provider.load_balancing_weight = None

        commit_to_db(restore_provider_details, weighted_provider, unweighted_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(self.default_type)
        assert actual_providers == [weighted_provider]

    def test_gets_active(self, restore_provider_details):
        active_provider = self.provider_factory(active=True)
        inactive_provider = self.provider_factory(active=False)

        commit_to_db(restore_provider_details, active_provider, inactive_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(self.default_type)
        assert actual_providers == [active_provider]

    def test_gets_international(self, restore_provider_details):
        international_provider = self.provider_factory(supports_international=True)
        non_international_provider = self.provider_factory(supports_international=False)

        commit_to_db(restore_provider_details, international_provider, non_international_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(self.default_type, True)
        assert actual_providers == [international_provider]

    def test_returns_empty_list(self, restore_provider_details):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)

        commit_to_db(restore_provider_details, email_provider)

        actual_providers = get_active_providers_with_weights_by_notification_type(NotificationType.SMS)
        assert actual_providers == []


@pytest.mark.serial
def test_should_not_error_if_any_provider_in_code_not_in_database(restore_provider_details):
    stmt = delete(ProviderDetails).where(ProviderDetails.identifier == 'sns')
    restore_provider_details.session.execute(stmt)
    restore_provider_details.session.commit()

    assert clients.get_sms_client('sns')


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
@freeze_time('2000-01-01T00:00:00')
def test_update_adds_history(restore_provider_details, sample_provider):
    sample_provider(notification_type=EMAIL_TYPE, identifier=SES_PROVIDER)

    stmt = select(ProviderDetails).where(ProviderDetails.identifier == SES_PROVIDER)
    ses = restore_provider_details.session.scalars(stmt).one()

    stmt = select(ProviderDetailsHistory).where(ProviderDetailsHistory.id == ses.id)
    ses_history = restore_provider_details.session.scalars(stmt).one()

    assert ses.version == 1
    assert ses_history.version == 1
    assert ses.updated_at is not None

    ses.active = False

    dao_update_provider_details(ses)

    assert not ses.active
    assert ses.updated_at == datetime(2000, 1, 1, 0, 0, 0)

    stmt = (
        select(ProviderDetailsHistory)
        .where(ProviderDetailsHistory.id == ses.id)
        .order_by(ProviderDetailsHistory.version)
    )
    ses_history = restore_provider_details.session.scalars(stmt).all()

    assert ses_history[0].active
    assert ses_history[0].version == 1
    assert ses_history[0].updated_at is not None

    assert not ses_history[1].active
    assert ses_history[1].version == 2
    assert ses_history[1].updated_at == datetime(2000, 1, 1, 0, 0, 0)


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_updated_at(restore_provider_details, sample_provider):
    """
    Updating an instance of ProviderDetails should automatically update the record's "updated_at"
    attribute and the same attribute in the associated ProviderDetailsHistory record.
    """

    sample_provider(notification_type=EMAIL_TYPE, identifier=SES_PROVIDER)

    stmt = select(ProviderDetails).where(ProviderDetails.identifier == SES_PROVIDER)
    ses = restore_provider_details.session.scalars(stmt).one()

    stmt = select(ProviderDetailsHistory).where(ProviderDetailsHistory.id == ses.id)
    ses_history = restore_provider_details.session.scalars(stmt).one()

    # These attributes are not nullible.
    assert ses.updated_at is not None and isinstance(ses.updated_at, datetime)
    assert ses_history.updated_at is not None and isinstance(ses_history.updated_at, datetime)

    ses_updated_at_initial = ses.updated_at
    ses_history_updated_at_initial = ses_history.updated_at

    # This should automatically set the records' "updated_at" field to the current time.
    dao_update_provider_details(ses)

    assert ses.updated_at is not None and ses.updated_at > ses_updated_at_initial

    stmt = (
        select(ProviderDetailsHistory)
        .where(ProviderDetailsHistory.id == ses.id)
        .order_by(desc(ProviderDetailsHistory.updated_at))
    )
    ses_history_new = restore_provider_details.session.scalars(stmt).first()

    assert ses_history_new.updated_at is not None and ses_history_new.updated_at > ses_history_updated_at_initial


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_update_sms_provider_to_inactive_sets_inactive(restore_provider_details, sample_provider):
    sample_provider(notification_type=SMS_TYPE, identifier=SNS_PROVIDER, priority=10)
    sample_provider(notification_type=SMS_TYPE, identifier=SES_PROVIDER, priority=15)

    set_primary_sms_provider(SNS_PROVIDER)
    primary_provider = get_current_provider(SMS_TYPE)
    primary_provider.active = False

    dao_update_provider_details(primary_provider)

    assert not primary_provider.active


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_get_current_sms_provider_returns_provider_highest_priority_active_provider(setup_sms_providers):
    provider = get_current_provider(SMS_TYPE)
    assert provider.identifier == setup_sms_providers[1].identifier


@pytest.mark.serial
def test_get_alternative_sms_provider_returns_next_highest_priority_active_sms_provider(setup_provider_details):
    active_sms_providers = [
        provider for provider in setup_provider_details if provider.notification_type == SMS_TYPE and provider.active
    ]

    for provider in active_sms_providers:
        alternative_provider = get_alternative_sms_provider(provider.identifier)

        assert alternative_provider.identifier != provider.identifier
        assert alternative_provider.active


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_switch_sms_provider_to_current_provider_does_not_switch(notify_user, sample_provider):
    pinpoint_provider = sample_provider()
    assert pinpoint_provider.notification_type == SMS_TYPE
    assert pinpoint_provider.identifier == PINPOINT_PROVIDER
    assert pinpoint_provider.priority == 10

    sns_provider = sample_provider(identifier=SNS_PROVIDER, priority=11)
    assert sns_provider.notification_type == SMS_TYPE
    assert sns_provider.identifier == SNS_PROVIDER
    assert sns_provider.priority == 11

    assert get_current_provider(SMS_TYPE).id == pinpoint_provider.id

    dao_switch_sms_provider_to_provider_with_identifier(SNS_PROVIDER)
    new_provider = get_current_provider(SMS_TYPE)

    assert new_provider.id == sns_provider.id
    assert new_provider.identifier == SNS_PROVIDER


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_switch_sms_provider_to_inactive_provider_does_not_switch(setup_sms_providers):
    [inactive_provider, current_provider, _] = setup_sms_providers
    assert get_current_provider(SMS_TYPE).identifier == current_provider.identifier

    dao_switch_sms_provider_to_provider_with_identifier(inactive_provider.identifier)
    new_provider = get_current_provider(SMS_TYPE)

    assert new_provider.id == current_provider.id
    assert new_provider.identifier == current_provider.identifier


@pytest.mark.skip(reason='#962 - provider swap is not used')
def test_toggle_sms_provider_should_not_switch_provider_if_no_alternate_provider(notify_api, mocker):
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=None)
    mock_dao_switch_sms_provider_to_provider_with_identifier = mocker.patch(
        'app.dao.provider_details_dao.dao_switch_sms_provider_to_provider_with_identifier'
    )
    dao_toggle_sms_provider('some-identifier')

    mock_dao_switch_sms_provider_to_provider_with_identifier.assert_not_called()


@pytest.mark.skip(reason='#962 - provider swap is not used')
def test_toggle_sms_provider_switches_provider(mocker, sample_user, setup_sms_providers):
    [inactive_provider, old_provider, alternative_provider] = setup_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user())
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)
    dao_toggle_sms_provider(old_provider.identifier)
    new_provider = get_current_provider(SMS_TYPE)

    assert new_provider.identifier != old_provider.identifier
    assert new_provider.priority < old_provider.priority


@pytest.mark.skip(reason='#962 - provider swap is not used')
def test_toggle_sms_provider_switches_when_provider_priorities_are_equal(
    mocker, sample_user, setup_equal_priority_sms_providers
):
    [old_provider, alternative_provider] = setup_equal_priority_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user())
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    dao_toggle_sms_provider(old_provider.identifier)
    new_provider = get_current_provider(SMS_TYPE)

    assert new_provider.identifier != old_provider.identifier
    assert new_provider.priority < old_provider.priority
    assert old_provider.priority == new_provider.priority + 10


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_toggle_sms_provider_updates_provider_history(notify_db_session, mocker, sample_user, setup_sms_providers):
    _, current_provider, alternative_provider = setup_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user())
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    # [ProviderDetailsHistory]
    current_provider_history = dao_get_provider_versions(current_provider.id)
    assert any(history.id == current_provider.id for history in current_provider_history)
    current_version = current_provider.version
    current_priority = current_provider.priority

    # [ProviderDetailsHistory]
    alternative_provider_history = dao_get_provider_versions(alternative_provider.id)
    assert any(history.id == alternative_provider.id for history in alternative_provider_history)
    alternative_version = alternative_provider.version
    alternative_priority = alternative_provider.priority

    # Switch provider from "current" to "alternative".  This should swap their priority.
    dao_toggle_sms_provider(current_provider.identifier)

    notify_db_session.session.refresh(current_provider)
    notify_db_session.session.refresh(alternative_provider)

    updated_current_provider_history = dao_get_provider_versions(current_provider.id)

    # The old+current version is in history.
    assert any(
        (
            history.id == current_provider.id
            and history.version == current_version
            and history.priority == current_priority
        )
        for history in updated_current_provider_history
    )

    # The updated+current version is in history.
    assert any(
        (
            history.id == current_provider.id
            and history.version == (current_version + 1)
            and history.priority == alternative_priority
        )
        for history in updated_current_provider_history
    )

    updated_alternative_provider_history = dao_get_provider_versions(alternative_provider.id)

    # The old+alternative version is in history.
    assert any(
        (
            history.id == alternative_provider.id
            and history.version == alternative_version
            and history.priority == alternative_priority
        )
        for history in updated_alternative_provider_history
    )

    # The updated+alternative version is in history.
    assert any(
        (
            history.id == alternative_provider.id
            and history.version == (alternative_version + 1)
            and history.priority == current_priority
        )
        for history in updated_alternative_provider_history
    )


@pytest.mark.skip(reason='#1631 - This test leaves a ProviderDetailsHistory instance that fails other tests.')
@pytest.mark.serial
def test_toggle_sms_provider_switches_provider_stores_notify_user_id(mocker, sample_user, setup_sms_providers):
    user = sample_user()
    _, current_provider, alternative_provider = setup_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=user)
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    # TODO 1631 - This seems to be creating an updated Twilio row in provider_details_history.
    dao_toggle_sms_provider(current_provider.identifier)
    new_provider = get_current_provider(SMS_TYPE)

    assert current_provider.identifier != new_provider.identifier
    assert new_provider.created_by.id == user.id
    assert new_provider.created_by_id == user.id


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_toggle_sms_provider_switches_provider_stores_notify_user_id_in_history(
    notify_db_session, mocker, sample_user, setup_sms_providers
):
    user = sample_user()
    _, old_provider, alternative_provider = setup_sms_providers
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=user)
    mocker.patch('app.dao.provider_details_dao.get_alternative_sms_provider', return_value=alternative_provider)

    dao_toggle_sms_provider(old_provider.identifier)
    new_provider = get_current_provider(SMS_TYPE)

    stmt = (
        select(ProviderDetailsHistory)
        .where(
            ProviderDetailsHistory.identifier == old_provider.identifier,
            ProviderDetailsHistory.version == old_provider.version,
        )
        .order_by(ProviderDetailsHistory.priority)
    )
    old_provider_from_history = notify_db_session.session.scalars(stmt).first()

    stmt = (
        select(ProviderDetailsHistory)
        .where(
            ProviderDetailsHistory.identifier == new_provider.identifier,
            ProviderDetailsHistory.version == new_provider.version,
        )
        .order_by(ProviderDetailsHistory.priority)
    )
    new_provider_from_history = notify_db_session.session.scalars(stmt).first()

    assert old_provider.version == old_provider_from_history.version
    assert new_provider.version == new_provider_from_history.version
    assert new_provider_from_history.created_by_id == user.id
    assert old_provider_from_history.created_by_id == user.id


@pytest.mark.skip(reason='#1436 - This test leaves a ProviderDetailsHistory instance that fails other tests.')
@pytest.mark.serial
def test_can_get_all_provider_history_with_newest_first(setup_sms_providers):
    _, current_provider, alternative_provider = setup_sms_providers
    current_provider.priority += 1
    dao_update_provider_details(current_provider)
    versions = dao_get_provider_versions(current_provider.id)
    assert len(versions) == 2
    assert versions[0].version == 2


@pytest.mark.serial
def test_get_sms_provider_with_equal_priority_returns_provider(setup_equal_priority_sms_providers):
    [current_provider, alternative_provider] = setup_equal_priority_sms_providers

    conflicting_provider = dao_get_sms_provider_with_equal_priority(
        current_provider.identifier, current_provider.priority
    )

    assert conflicting_provider.identifier == alternative_provider.identifier


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
def test_get_current_sms_provider_returns_active_only(
    sample_provider,
):
    provider = sample_provider(notification_type=SMS_TYPE, active=False)
    assert provider, 'Need one set'

    new_current_provider = get_current_provider(SMS_TYPE)
    assert new_current_provider is None


@pytest.mark.xfail(reason='#1631', run=False)
@pytest.mark.serial
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


@pytest.mark.serial
@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_ignores_billable_sms_older_than_1_month(
    sample_service,
    sample_template,
    setup_provider_details,
    sample_ft_billing,
):
    service = sample_service()
    sms_provider = next(
        (provider for provider in setup_provider_details if provider.notification_type == SMS_TYPE), None
    )
    sms_template = sample_template(service=service, template_type=SMS_TYPE)

    sample_ft_billing('2017-06-05', SMS_TYPE, sms_template, service, provider=sms_provider.identifier, billable_unit=4)

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 0


@pytest.mark.serial
@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_counts_billable_sms_within_last_month(
    sample_service,
    sample_template,
    setup_provider_details,
    sample_ft_billing,
):
    service = sample_service()
    sms_provider = next(
        (provider for provider in setup_provider_details if provider.notification_type == SMS_TYPE), None
    )
    sms_template = sample_template(service=service, template_type=SMS_TYPE)

    sample_ft_billing('2018-06-05', SMS_TYPE, sms_template, service, provider=sms_provider.identifier, billable_unit=4)

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 4


@pytest.mark.serial
@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_counts_billable_sms_within_last_month_with_rate_multiplier(
    sample_service,
    sample_template,
    setup_provider_details,
    sample_ft_billing,
):
    service = sample_service()
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    sms_provider = next(
        (provider for provider in setup_provider_details if provider.notification_type == SMS_TYPE), None
    )

    sample_ft_billing(
        '2018-06-05',
        SMS_TYPE,
        sms_template,
        service,
        provider=sms_provider.identifier,
        billable_unit=4,
        rate_multiplier=2,
    )

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 8

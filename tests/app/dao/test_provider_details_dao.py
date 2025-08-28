from datetime import datetime
from uuid import uuid4

import pytest
from freezegun import freeze_time
from sqlalchemy import delete, desc, select

from app import clients
from app.constants import EMAIL_TYPE, SES_PROVIDER, SMS_TYPE
from app.dao.provider_details_dao import (
    dao_get_provider_stats,
    dao_get_provider_versions,
    dao_update_provider_details,
    get_highest_priority_active_provider_identifier_by_notification_type,
)
from app.models import (
    ProviderDetails,
    ProviderDetailsHistory,
    ProviderRates,
)
from app.notifications.notification_type import NotificationType


@pytest.fixture
def setup_provider_details(sample_provider) -> list[ProviderDetails]:
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

        assert (
            get_highest_priority_active_provider_identifier_by_notification_type(NotificationType.EMAIL.value)
            == email_provider.identifier
        )

        assert (
            get_highest_priority_active_provider_identifier_by_notification_type(NotificationType.SMS.value)
            == sms_provider.identifier
        )

    def test_gets_higher_priority(self, restore_provider_details):
        low_number_priority_provider = self.provider_factory(priority=10)
        high_number_priority_provider = self.provider_factory(priority=50)

        commit_to_db(restore_provider_details, low_number_priority_provider, high_number_priority_provider)

        actual_provider = get_highest_priority_active_provider_identifier_by_notification_type(self.default_type.value)
        assert actual_provider == low_number_priority_provider.identifier

    def test_gets_active(self, restore_provider_details):
        active_provider = self.provider_factory(active=True)
        inactive_provider = self.provider_factory(active=False)

        commit_to_db(restore_provider_details, active_provider, inactive_provider)

        actual_provider = get_highest_priority_active_provider_identifier_by_notification_type(self.default_type.value)
        assert actual_provider == active_provider.identifier

    def test_gets_international(self, restore_provider_details):
        international_provider = self.provider_factory(supports_international=True)
        non_international_provider = self.provider_factory(supports_international=False)

        commit_to_db(restore_provider_details, international_provider, non_international_provider)

        actual_provider = get_highest_priority_active_provider_identifier_by_notification_type(
            self.default_type.value, True
        )
        assert actual_provider == international_provider.identifier

    def test_returns_none(self, restore_provider_details):
        email_provider = self.provider_factory(notification_type=NotificationType.EMAIL)

        commit_to_db(restore_provider_details, email_provider)

        actual_provider = get_highest_priority_active_provider_identifier_by_notification_type(
            NotificationType.SMS.value, True
        )
        assert actual_provider is None


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


@pytest.mark.skip(reason='#1436 - This test leaves a ProviderDetailsHistory instance that fails other tests.')
@pytest.mark.serial
def test_can_get_all_provider_history_with_newest_first(setup_sms_providers):
    _, current_provider, alternative_provider = setup_sms_providers
    current_provider.priority += 1
    dao_update_provider_details(current_provider)
    versions = dao_get_provider_versions(current_provider.id)
    assert len(versions) == 2
    assert versions[0].version == 2


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

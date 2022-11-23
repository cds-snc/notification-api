from datetime import datetime
from typing import Optional, List

from flask import current_app
from notifications_utils.timezones import convert_utc_to_local_timezone
from sqlalchemy import asc, desc, func

from app.dao.dao_utils import transactional
from app.notifications.notification_type import NotificationType
from app.provider_details.switch_providers import (
    provider_is_inactive,
    provider_is_primary,
    switch_providers
)
from app.models import FactBilling, ProviderDetails, ProviderDetailsHistory, SMS_TYPE
from app.model import User
from app import db


def get_provider_details_by_id(provider_details_id) -> Optional[ProviderDetails]:
    return ProviderDetails.query.get(provider_details_id)


def get_provider_details_by_identifier(identifier):
    return ProviderDetails.query.filter_by(identifier=identifier).one()


# TODO #962 - Should this be deleted? sms provider swap code
def get_alternative_sms_provider(identifier: str) -> Optional[ProviderDetails]:
    """
    Return the highest priority SMS provider that doesn't match the given
    identifier.

    If this function is deleted, we don't have to worry about the below.
    TODO #957 - This would be more elegant as a method on a custom query class for the ProviderDetails model.
    https://stackoverflow.com/questions/15936111/sqlalchemy-can-you-add-custom-methods-to-the-query-object
    """

    return ProviderDetails.query.filter_by(
        notification_type=SMS_TYPE,
        active=True
    ).filter(
        ProviderDetails.identifier != identifier
    ).order_by(
        asc(ProviderDetails.priority)
    ).first()


def get_current_provider(notification_type):
    return ProviderDetails.query.filter_by(
        notification_type=notification_type,
        active=True
    ).order_by(
        asc(ProviderDetails.priority)
    ).first()


def dao_get_provider_versions(provider_id):
    return ProviderDetailsHistory.query.filter_by(
        id=provider_id
    ).order_by(
        desc(ProviderDetailsHistory.version)
    ).all()

# TODO #962 - Should this be deleted? sms provider swap code
@transactional
def dao_toggle_sms_provider(identifier):
    alternate_provider = get_alternative_sms_provider(identifier)
    if alternate_provider is not None:
        dao_switch_sms_provider_to_provider_with_identifier(alternate_provider.identifier)
    else:
        current_app.logger.warning('Cancelling switch from %s as there is no alternative provider.', identifier)

# TODO #962 - Should this be deleted? sms provider swap code
@transactional
def dao_switch_sms_provider_to_provider_with_identifier(identifier):
    new_provider = get_provider_details_by_identifier(identifier)

    if provider_is_inactive(new_provider):
        return

    # Check first to see if there is another provider with the same priority
    # as this needs to be updated differently
    conflicting_provider = dao_get_sms_provider_with_equal_priority(new_provider.identifier, new_provider.priority)
    providers_to_update = []

    if conflicting_provider:
        switch_providers(conflicting_provider, new_provider)
    else:
        current_provider = get_current_provider('sms')
        if not provider_is_primary(current_provider, new_provider, identifier):
            providers_to_update = switch_providers(current_provider, new_provider)

        for provider in providers_to_update:
            dao_update_provider_details(provider)


def get_provider_details_by_notification_type(notification_type, supports_international=False):

    filters = [ProviderDetails.notification_type == notification_type]

    if supports_international:
        filters.append(ProviderDetails.supports_international == supports_international)

    return ProviderDetails.query.filter(*filters).order_by(asc(ProviderDetails.priority)).all()


def get_highest_priority_active_provider_by_notification_type(
        notification_type: NotificationType,
        supports_international: bool = False
) -> Optional[ProviderDetails]:
    filters = [
        ProviderDetails.notification_type == notification_type.value,
        ProviderDetails.active == True # noqa
    ]

    if supports_international:
        filters.append(ProviderDetails.supports_international == supports_international)

    return ProviderDetails.query.filter(*filters).order_by(asc(ProviderDetails.priority)).first()


def get_active_providers_with_weights_by_notification_type(
        notification_type: NotificationType,
        supports_international: bool = False
) -> List[ProviderDetails]:
    filters = [
        ProviderDetails.notification_type == notification_type.value,
        ProviderDetails.load_balancing_weight != None, # noqa
        ProviderDetails.active == True # noqa
    ]

    if supports_international:
        filters.append(ProviderDetails.supports_international == supports_international)

    return ProviderDetails.query.filter(*filters).all()


@transactional
def dao_update_provider_details(provider_details):
    provider_details.version += 1
    provider_details.updated_at = datetime.utcnow()
    history = ProviderDetailsHistory.from_original(provider_details)
    db.session.add(provider_details)
    db.session.add(history)


# TODO #962 - Should this be deleted? sms provider swap code
def dao_get_sms_provider_with_equal_priority(identifier, priority):
    provider = db.session.query(ProviderDetails).filter(
        ProviderDetails.identifier != identifier,
        ProviderDetails.notification_type == 'sms',
        ProviderDetails.priority == priority,
        ProviderDetails.active
    ).order_by(
        asc(ProviderDetails.priority)
    ).first()

    return provider


def dao_get_provider_stats():
    # this query does not include the current day since the task to populate ft_billing runs overnight

    current_local_datetime = convert_utc_to_local_timezone(datetime.utcnow())
    first_day_of_the_month = current_local_datetime.date().replace(day=1)

    subquery = db.session.query(
        FactBilling.provider,
        func.sum(FactBilling.billable_units * FactBilling.rate_multiplier).label('current_month_billable_sms')
    ).filter(
        FactBilling.notification_type == SMS_TYPE,
        FactBilling.bst_date >= first_day_of_the_month
    ).group_by(
        FactBilling.provider
    ).subquery()

    result = db.session.query(
        ProviderDetails.id,
        ProviderDetails.display_name,
        ProviderDetails.identifier,
        ProviderDetails.priority,
        ProviderDetails.load_balancing_weight,
        ProviderDetails.notification_type,
        ProviderDetails.active,
        ProviderDetails.updated_at,
        ProviderDetails.supports_international,
        User.name.label('created_by_name'),
        func.coalesce(subquery.c.current_month_billable_sms, 0).label('current_month_billable_sms')
    ).outerjoin(
        subquery, ProviderDetails.identifier == subquery.c.provider
    ).outerjoin(
        User, ProviderDetails.created_by_id == User.id
    ).order_by(
        ProviderDetails.notification_type,
        ProviderDetails.priority,
    ).all()

    return result

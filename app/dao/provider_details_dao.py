from datetime import datetime

from cachetools import cached, TTLCache
from flask import current_app
from notifications_utils.timezones import convert_utc_to_local_timezone
from sqlalchemy import asc, desc, func, select

from app.dao.dao_utils import transactional
from app.notifications.notification_type import NotificationType
from app.provider_details.switch_providers import (
    provider_is_inactive,
    provider_is_primary,
    switch_providers,
)
from app.models import FactBilling, ProviderDetails, ProviderDetailsData, ProviderDetailsHistory, SMS_TYPE
from app.model import User
from app import db


@cached(cache=TTLCache(maxsize=1024, ttl=600))
def get_provider_details_by_id(provider_details_id) -> ProviderDetailsData | None:
    provider = db.session.get(ProviderDetails, provider_details_id)

    if provider is None:
        return None

    return ProviderDetailsData(
        active=provider.active,
        display_name=provider.display_name,
        identifier=provider.identifier,
        notification_type=provider.notification_type,
    )


def dao_get_provider_versions(provider_id):
    stmt = (
        select(ProviderDetailsHistory)
        .where(ProviderDetailsHistory.id == provider_id)
        .order_by(desc(ProviderDetailsHistory.version))
    )

    return db.session.scalars(stmt).all()


@cached(cache=TTLCache(maxsize=1024, ttl=600))
def get_highest_priority_active_provider_identifier_by_notification_type(
    notification_type: str, supports_international: bool = False
) -> str | None:
    """
    Note that the highest priority provider is the one with the lowest value for "priority".
    Lower values have higher precedence.
    """

    filters = [ProviderDetails.notification_type == notification_type, ProviderDetails.active.is_(True)]

    if supports_international:
        filters.append(ProviderDetails.supports_international == supports_international)

    stmt = select(ProviderDetails).where(*filters).order_by(asc(ProviderDetails.priority))
    provider_details = db.session.scalars(stmt).first()

    return None if (provider_details is None) else provider_details.identifier


@transactional
def dao_update_provider_details(provider_details):
    provider_details.version += 1
    provider_details.updated_at = datetime.utcnow()
    history = ProviderDetailsHistory.from_original(provider_details)
    db.session.add(provider_details)
    db.session.add(history)


def dao_get_provider_stats():
    # this query does not include the current day since the task to populate ft_billing runs overnight

    current_local_datetime = convert_utc_to_local_timezone(datetime.utcnow())
    first_day_of_the_month = current_local_datetime.date().replace(day=1)

    sub_result = (
        select(
            FactBilling.provider,
            func.sum(FactBilling.billable_units * FactBilling.rate_multiplier).label('current_month_billable_sms'),
        )
        .where(FactBilling.notification_type == SMS_TYPE, FactBilling.bst_date >= first_day_of_the_month)
        .group_by(FactBilling.provider)
        .subquery()
    )

    stmt = (
        select(
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
            func.coalesce(sub_result.c.current_month_billable_sms, 0).label('current_month_billable_sms'),
        )
        .outerjoin(sub_result, ProviderDetails.identifier == sub_result.c.provider)
        .outerjoin(User, ProviderDetails.created_by_id == User.id)
        .order_by(
            ProviderDetails.notification_type,
            ProviderDetails.priority,
        )
    )

    return db.session.execute(stmt).all()

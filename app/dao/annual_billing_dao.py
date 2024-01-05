from app import db
from app.dao.dao_utils import transactional
from app.dao.date_util import get_current_financial_year_start_year
from app.models import AnnualBilling
from sqlalchemy import select, update


@transactional
def dao_create_or_update_annual_billing_for_year(service_id, free_sms_fragment_limit, financial_year_start):
    result = dao_get_free_sms_fragment_limit_for_year(service_id, financial_year_start)

    if result:
        result.free_sms_fragment_limit = free_sms_fragment_limit
    else:
        result = AnnualBilling(service_id=service_id, financial_year_start=financial_year_start,
                               free_sms_fragment_limit=free_sms_fragment_limit)
    db.session.add(result)
    return result


def dao_get_annual_billing(service_id):
    stmt = select(AnnualBilling).where(
        AnnualBilling.service_id == service_id
    ).order_by(
        AnnualBilling.financial_year_start
    )

    return db.session.scalars(stmt).all()


@transactional
def dao_update_annual_billing_for_future_years(service_id, free_sms_fragment_limit, financial_year_start):
    stmt = update(AnnualBilling).where(
        AnnualBilling.service_id == service_id,
        AnnualBilling.financial_year_start > financial_year_start
    ).values(free_sms_fragment_limit=free_sms_fragment_limit)

    db.session.execute(stmt)


def dao_get_free_sms_fragment_limit_for_year(service_id, financial_year_start=None):

    if not financial_year_start:
        financial_year_start = get_current_financial_year_start_year()

    stmt = select(AnnualBilling).where(
        AnnualBilling.service_id == service_id,
        AnnualBilling.financial_year_start == financial_year_start
    )

    return db.session.scalars(stmt).first()


def dao_get_all_free_sms_fragment_limit(service_id):
    stmt = select(AnnualBilling).where(
        AnnualBilling.service_id == service_id
    ).order_by(
        AnnualBilling.financial_year_start
    )

    return db.session.scalars(stmt).all()

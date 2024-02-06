from app.dao.annual_billing_dao import (
    dao_create_or_update_annual_billing_for_year,
    dao_get_free_sms_fragment_limit_for_year,
    dao_update_annual_billing_for_future_years,
)
from app.dao.date_util import get_current_financial_year_start_year
from tests.app.db import create_annual_billing


def test_dao_update_free_sms_fragment_limit(sample_service):
    new_limit = 9999
    service = sample_service()
    year = get_current_financial_year_start_year()
    dao_create_or_update_annual_billing_for_year(service.id, new_limit, year)
    new_free_limit = dao_get_free_sms_fragment_limit_for_year(service.id, year)

    assert new_free_limit.free_sms_fragment_limit == new_limit


def test_create_annual_billing(sample_service):
    service = sample_service()
    dao_create_or_update_annual_billing_for_year(service.id, 9999, 2016)
    free_limit = dao_get_free_sms_fragment_limit_for_year(service.id, 2016)
    assert free_limit.free_sms_fragment_limit == 9999


def test_dao_update_annual_billing_for_future_years(sample_service):
    current_year = get_current_financial_year_start_year()
    limits = [1, 2, 3, 4]
    service = sample_service()
    create_annual_billing(service.id, limits[0], current_year - 1)
    create_annual_billing(service.id, limits[2], current_year + 1)
    create_annual_billing(service.id, limits[3], current_year + 2)

    dao_update_annual_billing_for_future_years(service.id, 9999, current_year)

    assert dao_get_free_sms_fragment_limit_for_year(service.id, current_year - 1).free_sms_fragment_limit == 1
    # current year is not created
    assert dao_get_free_sms_fragment_limit_for_year(service.id, current_year) is None
    assert dao_get_free_sms_fragment_limit_for_year(service.id, current_year + 1).free_sms_fragment_limit == 9999
    assert dao_get_free_sms_fragment_limit_for_year(service.id, current_year + 2).free_sms_fragment_limit == 9999

import pytest
from app.billing.rest import update_free_sms_fragment_limit_data
from app.dao.annual_billing_dao import dao_get_free_sms_fragment_limit_for_year
from app.dao.date_util import get_current_financial_year_start_year, get_month_start_and_end_date_in_utc
from app.models import (
    AnnualBilling,
    EMAIL_TYPE,
    FactBilling,
    LETTER_TYPE,
    SMS_TYPE,
)
from calendar import monthrange
from datetime import datetime, timedelta
from freezegun import freeze_time
from sqlalchemy import delete, func, select
from tests import create_admin_authorization_header
from tests.app.db import (
    create_annual_billing,
)


APR_2016_MONTH_START = datetime(2016, 3, 31, 23, 00, 00)
APR_2016_MONTH_END = datetime(2016, 4, 30, 22, 59, 59, 99999)

IN_MAY_2016 = datetime(2016, 5, 10, 23, 00, 00)
IN_JUN_2016 = datetime(2016, 6, 3, 23, 00, 00)


def test_create_update_free_sms_fragment_limit_invalid_schema(client, sample_service):
    service = sample_service()

    response = client.post(
        f'service/{service.id}/billing/free-sms-fragment-limit',
        data={},
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
    )

    assert response.status_code == 400
    assert 'JSON' in response.get_json()['message']


def test_create_free_sms_fragment_limit_current_year_updates_future_years(
    notify_db_session, admin_request, sample_service
):
    service = sample_service()
    current_year = get_current_financial_year_start_year()
    future_billing = create_annual_billing(service.id, 1, current_year + 1)

    admin_request.post(
        'billing.create_or_update_free_sms_fragment_limit',
        service_id=service.id,
        _data={'free_sms_fragment_limit': 9999},
        _expected_status=201,
    )

    current_billing = dao_get_free_sms_fragment_limit_for_year(service.id, current_year)

    try:
        assert future_billing.free_sms_fragment_limit == 9999
        assert current_billing.financial_year_start == current_year
        assert current_billing.free_sms_fragment_limit == 9999
    finally:
        # Test clean-up
        notify_db_session.session.delete(future_billing)
        notify_db_session.session.commit()


@pytest.mark.parametrize('update_existing', [True, False])
def test_create_or_update_free_sms_fragment_limit_past_year_doenst_update_other_years(
    admin_request, sample_service, update_existing
):
    service = sample_service()
    current_year = get_current_financial_year_start_year()
    create_annual_billing(service.id, 1, current_year)
    if update_existing:
        create_annual_billing(service.id, 1, current_year - 1)

    data = {
        'financial_year_start': current_year - 1,
        'free_sms_fragment_limit': 9999,
    }

    admin_request.post(
        'billing.create_or_update_free_sms_fragment_limit', service_id=service.id, _data=data, _expected_status=201
    )

    assert dao_get_free_sms_fragment_limit_for_year(service.id, current_year - 1).free_sms_fragment_limit == 9999
    assert dao_get_free_sms_fragment_limit_for_year(service.id, current_year).free_sms_fragment_limit == 1


def test_create_free_sms_fragment_limit_updates_existing_year(admin_request, sample_service):
    service = sample_service()
    current_year = get_current_financial_year_start_year()
    annual_billing = create_annual_billing(service.id, 1, current_year)

    admin_request.post(
        'billing.create_or_update_free_sms_fragment_limit',
        service_id=service.id,
        _data={'financial_year_start': current_year, 'free_sms_fragment_limit': 2},
        _expected_status=201,
    )

    assert annual_billing.free_sms_fragment_limit == 2


def test_get_free_sms_fragment_limit_current_year_creates_new_row(client, notify_db_session, sample_service):
    service = sample_service()
    current_year = get_current_financial_year_start_year()
    create_annual_billing(service.id, 9999, current_year - 1)

    response_get = client.get(
        'service/{}/billing/free-sms-fragment-limit'.format(service.id),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
    )

    assert response_get.status_code == 200
    json_resp = response_get.get_json()
    assert json_resp['financial_year_start'] == get_current_financial_year_start_year()
    assert json_resp['free_sms_fragment_limit'] == 9999

    # Teardown
    stmt = select(AnnualBilling).where(AnnualBilling.service_id == service.id)
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


def test_get_free_sms_fragment_limit_past_year_not_exist(client, notify_db_session, sample_service):
    service = sample_service()
    current_year = get_current_financial_year_start_year()
    create_annual_billing(service.id, 9999, current_year - 1)
    create_annual_billing(service.id, 10000, current_year + 1)

    annual_billing = dao_get_free_sms_fragment_limit_for_year(service.id, current_year - 2)
    assert annual_billing is None

    res_get = client.get(
        'service/{}/billing/free-sms-fragment-limit?financial_year_start={}'.format(service.id, current_year - 2),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
    )

    assert res_get.status_code == 200
    json_resp = res_get.get_json()
    assert json_resp['financial_year_start'] == current_year - 1
    assert json_resp['free_sms_fragment_limit'] == 9999

    # Teardown
    stmt = select(AnnualBilling).where(AnnualBilling.service_id == service.id)
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


def test_get_free_sms_fragment_limit_future_year_not_exist(client, sample_service):
    service = sample_service()
    current_year = get_current_financial_year_start_year()
    create_annual_billing(service.id, free_sms_fragment_limit=9999, financial_year_start=current_year - 1)
    create_annual_billing(service.id, free_sms_fragment_limit=10000, financial_year_start=current_year + 1)

    annual_billing = dao_get_free_sms_fragment_limit_for_year(service.id, current_year + 2)
    assert annual_billing is None

    res_get = client.get(
        'service/{}/billing/free-sms-fragment-limit?financial_year_start={}'.format(service.id, current_year + 2),
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
    )

    assert res_get.status_code == 200
    json_resp = res_get.get_json()
    assert json_resp['financial_year_start'] == current_year + 2
    assert json_resp['free_sms_fragment_limit'] == 10000


def test_update_free_sms_fragment_limit_data(client, sample_service):
    service = sample_service()
    current_year = get_current_financial_year_start_year()
    create_annual_billing(service.id, free_sms_fragment_limit=250000, financial_year_start=current_year - 1)
    update_free_sms_fragment_limit_data(service.id, 9999, current_year)
    annual_billing = dao_get_free_sms_fragment_limit_for_year(service.id, current_year)
    assert annual_billing.free_sms_fragment_limit == 9999


@pytest.mark.serial
@freeze_time('1990-04-21 14:00')
def test_get_yearly_usage_by_monthly_from_ft_billing_populates_deltas(
    notify_db_session,
    client,
    sample_service,
    sample_template,
    sample_notification,
    sample_rate,
):
    service = sample_service()
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    assert sms_template.template_type == SMS_TYPE
    sample_rate(start_date=datetime.utcnow() - timedelta(days=1), value=0.158, notification_type=SMS_TYPE)

    notification = sample_notification(template=sms_template, status='delivered')
    assert notification.status == 'delivered'

    stmt = select(func.count()).select_from(FactBilling).where(FactBilling.service_id == service.id)
    assert notify_db_session.session.scalar(stmt) == 0

    try:
        # This request has the side-effect of creating a FactBilling instance in the ft_billing table.
        # But it's a GET request?
        response = client.get(
            f'service/{service.id}/billing/ft-monthly-usage?year=1990',
            headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
        )

        assert response.status_code == 200
        assert len(response.get_json()) == 1
        stmt = select(FactBilling).where(FactBilling.service_id == service.id)
        fact_billing = notify_db_session.session.scalars(stmt).all()

        assert len(fact_billing) == 1
        assert fact_billing[0].notification_type == SMS_TYPE

    finally:
        # Teardown due to side effect of the GET request
        stmt = delete(FactBilling).where(FactBilling.service_id == service.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


# This test takes a long time to run.
@pytest.mark.serial
def test_get_yearly_usage_by_monthly_from_ft_billing(
    client,
    notify_db_session,
    sample_service,
    sample_ft_billing,
    sample_template,
):

    service = sample_service()
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)

    for month in range(1, 13):
        mon = str(month).zfill(2)

        for day in range(1, monthrange(2016, month)[1] + 1):
            d = str(day).zfill(2)

            sample_ft_billing(
                utc_date='2016-{}-{}'.format(mon, d),
                service=service,
                template=sms_template,
                notification_type=SMS_TYPE,
                billable_unit=1,
                rate=0.162,
            )

            sample_ft_billing(
                utc_date='2016-{}-{}'.format(mon, d),
                service=service,
                template=email_template,
                notification_type=EMAIL_TYPE,
                rate=0,
            )

            sample_ft_billing(
                utc_date='2016-{}-{}'.format(mon, d),
                service=service,
                template=letter_template,
                notification_type=LETTER_TYPE,
                billable_unit=1,
                rate=0.33,
                postage='second',
            )

    try:
        # This request has the side-effect of creating a FactBilling instance in the ft_billing table.
        # But it's a GET request?
        response = client.get(
            f'service/{service.id}/billing/ft-monthly-usage?year=2016',
            headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
        )

        json_resp = response.get_json()
        ft_letters = [x for x in json_resp if x['notification_type'] == LETTER_TYPE]
        ft_sms = [x for x in json_resp if x['notification_type'] == SMS_TYPE]
        ft_email = [x for x in json_resp if x['notification_type'] == EMAIL_TYPE]
        keys = [x.keys() for x in ft_sms][0]

        expected_sms_april = {
            'month': 'April',
            'notification_type': SMS_TYPE,
            'billing_units': 30,
            'rate': 0.162,
            'postage': 'none',
        }

        expected_letter_april = {
            'month': 'April',
            'notification_type': LETTER_TYPE,
            'billing_units': 30,
            'rate': 0.33,
            'postage': 'second',
        }

        for k in keys:
            assert ft_sms[0][k] == expected_sms_april[k]
            assert ft_letters[0][k] == expected_letter_april[k]
        assert len(ft_email) == 0

    finally:
        # Teardown due to side effect of the GET request
        stmt = delete(FactBilling).where(FactBilling.service_id == service.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_get_yearly_billing_usage_summary_from_ft_billing_returns_400_if_missing_year(client, sample_service):
    service = sample_service()

    response = client.get(
        f'/service/{service.id}/billing/ft-yearly-usage-summary', headers=[create_admin_authorization_header()]
    )

    assert response.status_code == 400
    assert response.get_json() == {'message': 'No valid year provided', 'result': 'error'}


def test_get_yearly_billing_usage_summary_from_ft_billing_returns_empty_list_if_no_billing_data(client, sample_service):
    service = sample_service()

    response = client.get(
        f'/service/{service.id}/billing/ft-yearly-usage-summary?year=2016',
        headers=[create_admin_authorization_header()],
    )

    assert response.status_code == 200
    assert response.get_json() == []


# This test takes a long time to run.
@pytest.mark.serial
def test_get_yearly_billing_usage_summary_from_ft_billing(
    notify_db_session,
    client,
    sample_ft_billing,
    sample_service,
    sample_template,
):

    service = sample_service()
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)

    for month in range(1, 13):
        mon = str(month).zfill(2)

        for day in range(1, monthrange(2016, month)[1] + 1):
            d = str(day).zfill(2)

            sample_ft_billing(
                utc_date='2016-{}-{}'.format(mon, d),
                notification_type=SMS_TYPE,
                template=sms_template,
                service=service,
                rate=0.0162,
            )

            sample_ft_billing(
                utc_date='2016-{}-{}'.format(mon, d),
                notification_type=SMS_TYPE,
                template=sms_template,
                service=service,
                rate_multiplier=2,
                rate=0.0162,
            )

            sample_ft_billing(
                utc_date='2016-{}-{}'.format(mon, d),
                notification_type=EMAIL_TYPE,
                template=email_template,
                service=service,
                billable_unit=0,
                rate=0,
            )

            sample_ft_billing(
                utc_date='2016-{}-{}'.format(mon, d),
                notification_type=LETTER_TYPE,
                template=letter_template,
                service=service,
                rate=0.33,
                postage='second',
            )

        get_month_start_and_end_date_in_utc(datetime(2016, int(mon), 1))

    response = client.get(
        f'/service/{service.id}/billing/ft-yearly-usage-summary?year=2016',
        headers=[create_admin_authorization_header()],
    )

    assert response.status_code == 200
    json_response = response.get_json()
    assert len(json_response) == 3
    assert json_response[0]['notification_type'] == EMAIL_TYPE
    assert json_response[0]['billing_units'] == 275
    assert json_response[0]['rate'] == 0
    assert json_response[0]['letter_total'] == 0
    assert json_response[1]['notification_type'] == LETTER_TYPE
    assert json_response[1]['billing_units'] == 275
    assert json_response[1]['rate'] == 0.33
    assert json_response[1]['letter_total'] == 90.75
    assert json_response[2]['notification_type'] == SMS_TYPE
    assert json_response[2]['billing_units'] == 825
    assert json_response[2]['rate'] == 0.0162
    assert json_response[2]['letter_total'] == 0


def test_get_yearly_usage_by_monthly_from_ft_billing_all_cases(
    client, sample_service, sample_template,sample_ft_billing,
):
    service = sample_service()
    set_up_data_for_all_cases(service, sample_template,sample_ft_billing)

    response = client.get(
        f'service/{service.id}/billing/ft-monthly-usage?year=2018',
        headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
    )

    assert response.status_code == 200
    json_response = response.get_json()
    assert len(json_response) == 5
    assert json_response[0]['month'] == 'May'
    assert json_response[0]['notification_type'] == LETTER_TYPE
    assert json_response[0]['rate'] == 0.33
    assert json_response[0]['billing_units'] == 1
    assert json_response[0]['postage'] == 'second'

    assert json_response[1]['month'] == 'May'
    assert json_response[1]['notification_type'] == LETTER_TYPE
    assert json_response[1]['rate'] == 0.36
    assert json_response[1]['billing_units'] == 1
    assert json_response[1]['postage'] == 'second'

    assert json_response[2]['month'] == 'May'
    assert json_response[2]['notification_type'] == LETTER_TYPE
    assert json_response[2]['rate'] == 0.39
    assert json_response[2]['billing_units'] == 1
    assert json_response[2]['postage'] == 'first'

    assert json_response[3]['month'] == 'May'
    assert json_response[3]['notification_type'] == SMS_TYPE
    assert json_response[3]['rate'] == 0.0150
    assert json_response[3]['billing_units'] == 4
    assert json_response[3]['postage'] == 'none'

    assert json_response[4]['month'] == 'May'
    assert json_response[4]['notification_type'] == SMS_TYPE
    assert json_response[4]['rate'] == 0.162
    assert json_response[4]['billing_units'] == 5
    assert json_response[4]['postage'] == 'none'


def test_get_yearly_billing_usage_summary_from_ft_billing_all_cases(
    client, sample_service, sample_template, sample_ft_billing,
):
    service = sample_service()
    set_up_data_for_all_cases(service, sample_template, sample_ft_billing)

    response = client.get(
        f'/service/{service.id}/billing/ft-yearly-usage-summary?year=2018',
        headers=[create_admin_authorization_header()],
    )

    assert response.status_code == 200
    json_response = response.get_json()

    assert len(json_response) == 6
    assert json_response[0]['notification_type'] == EMAIL_TYPE
    assert json_response[0]['billing_units'] == 1
    assert json_response[0]['rate'] == 0
    assert json_response[0]['letter_total'] == 0

    assert json_response[1]['notification_type'] == LETTER_TYPE
    assert json_response[1]['billing_units'] == 1
    assert json_response[1]['rate'] == 0.33
    assert json_response[1]['letter_total'] == 0.33

    assert json_response[2]['notification_type'] == LETTER_TYPE
    assert json_response[2]['billing_units'] == 1
    assert json_response[2]['rate'] == 0.36
    assert json_response[2]['letter_total'] == 0.36

    assert json_response[3]['notification_type'] == LETTER_TYPE
    assert json_response[3]['billing_units'] == 1
    assert json_response[3]['rate'] == 0.39
    assert json_response[3]['letter_total'] == 0.39

    assert json_response[4]['notification_type'] == SMS_TYPE
    assert json_response[4]['billing_units'] == 4
    assert json_response[4]['rate'] == 0.0150
    assert json_response[4]['letter_total'] == 0

    assert json_response[5]['notification_type'] == SMS_TYPE
    assert json_response[5]['billing_units'] == 5
    assert json_response[5]['rate'] == 0.162
    assert json_response[5]['letter_total'] == 0


def set_up_data_for_all_cases(
    service,
    sample_template,
    sample_ft_billing,
) -> None:
    """
    Return setup common to multiple tests in this module.
    """

    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)

    sample_ft_billing(
        utc_date='2018-05-16',
        notification_type=SMS_TYPE,
        template=sms_template,
        service=service,
        rate_multiplier=1,
        international=False,
        rate=0.162,
        billable_unit=1,
        notifications_sent=1,
    )

    sample_ft_billing(
        utc_date='2018-05-17',
        notification_type=SMS_TYPE,
        template=sms_template,
        service=service,
        rate_multiplier=2,
        international=False,
        rate=0.162,
        billable_unit=2,
        notifications_sent=1,
    )

    sample_ft_billing(
        utc_date='2018-05-16',
        notification_type=SMS_TYPE,
        template=sms_template,
        service=service,
        rate_multiplier=2,
        international=False,
        rate=0.0150,
        billable_unit=2,
        notifications_sent=1,
    )

    sample_ft_billing(
        utc_date='2018-05-16',
        notification_type=EMAIL_TYPE,
        template=email_template,
        service=service,
        rate_multiplier=1,
        international=False,
        rate=0,
        billable_unit=0,
        notifications_sent=1,
    )

    sample_ft_billing(
        utc_date='2018-05-16',
        notification_type=LETTER_TYPE,
        template=letter_template,
        service=service,
        rate_multiplier=1,
        international=False,
        rate=0.33,
        billable_unit=1,
        notifications_sent=1,
        postage='second',
    )

    sample_ft_billing(
        utc_date='2018-05-17',
        notification_type=LETTER_TYPE,
        template=letter_template,
        service=service,
        rate_multiplier=1,
        international=False,
        rate=0.36,
        billable_unit=2,
        notifications_sent=1,
        postage='second',
    )

    sample_ft_billing(
        utc_date='2018-05-18',
        notification_type=LETTER_TYPE,
        template=letter_template,
        service=service,
        rate_multiplier=1,
        international=False,
        rate=0.39,
        billable_unit=3,
        notifications_sent=1,
        postage='first',
    )

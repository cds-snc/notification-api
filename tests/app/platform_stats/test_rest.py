from datetime import date, datetime

import pytest
from freezegun import freeze_time

from app.constants import SMS_TYPE, EMAIL_TYPE, NOTIFICATION_DELIVERED
from tests.app.factories.feature_flag import mock_feature_flag
from app.feature_flags import FeatureFlag
from app.platform_stats.rest import get_monthly_platform_stats


@freeze_time('2018-06-01')
def test_get_platform_stats_uses_todays_date_if_no_start_or_end_date_is_provided(admin_request, mocker):
    today = datetime.now().date()
    dao_mock = mocker.patch('app.platform_stats.rest.fetch_notification_status_totals_for_all_services')
    mocker.patch('app.service.rest.statistics.format_statistics')

    admin_request.get('platform_stats.get_platform_stats')

    dao_mock.assert_called_once_with(start_date=today, end_date=today)


def test_get_platform_stats_can_filter_by_date(admin_request, mocker):
    start_date = date(2017, 1, 1)
    end_date = date(2018, 1, 1)
    dao_mock = mocker.patch('app.platform_stats.rest.fetch_notification_status_totals_for_all_services')
    mocker.patch('app.service.rest.statistics.format_statistics')

    admin_request.get('platform_stats.get_platform_stats', start_date=start_date, end_date=end_date)

    dao_mock.assert_called_once_with(start_date=start_date, end_date=end_date)


def test_get_platform_stats_validates_the_date(admin_request):
    start_date = '1234-56-78'

    response = admin_request.get('platform_stats.get_platform_stats', start_date=start_date, _expected_status=400)

    assert response['errors'][0]['message'] == 'start_date month must be in 1..12'


@pytest.mark.serial
@freeze_time('1973-10-31 14:00')
def test_get_platform_stats_with_real_query(
    admin_request,
    sample_ft_notification_status,
    sample_notification,
    sample_service,
    sample_template,
    sample_job,
):
    service = sample_service()
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    sample_ft_notification_status(date(1973, 10, 29), sample_job(sms_template), count=10)
    sample_ft_notification_status(date(1973, 10, 29), sample_job(email_template), count=3)

    sample_notification(template=sms_template, created_at=datetime(1973, 10, 31, 11, 0, 0), key_type='test')
    sample_notification(template=sms_template, created_at=datetime(1973, 10, 31, 12, 0, 0), status='delivered')
    sample_notification(template=email_template, created_at=datetime(1973, 10, 31, 13, 0, 0), status='delivered')

    # Cannot be ran in parallel - has some sort of race condition
    response = admin_request.get(
        'platform_stats.get_platform_stats',
        start_date=date(1973, 10, 29),
        end_date=date(1973, 10, 31),
    )
    assert response == {
        'email': {
            'failures': {
                'virus-scan-failed': 0,
                'temporary-failure': 0,
                'permanent-failure': 0,
            },
            'total': 4,
            'test-key': 0,
        },
        'letter': {
            'failures': {
                'virus-scan-failed': 0,
                'temporary-failure': 0,
                'permanent-failure': 0,
            },
            'total': 0,
            'test-key': 0,
        },
        'sms': {
            'failures': {
                'virus-scan-failed': 0,
                'temporary-failure': 0,
                'permanent-failure': 0,
            },
            'total': 11,
            'test-key': 1,
        },
    }


@freeze_time('2020-01-25 00:00')
def test_get_platform_stats_response_when_toggle_is_on(
    sample_ft_notification_status,
    sample_service,
    sample_template,
    sample_job,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.PLATFORM_STATS_ENABLED, 'True')

    service = sample_service()
    sms_template = sample_template(service=service, template_type=SMS_TYPE)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    email_job = sample_job(email_template)

    sample_ft_notification_status(
        date(2022, 1, 1),
        email_job,
        notification_status=NOTIFICATION_DELIVERED,
        count=1,
    )

    sample_ft_notification_status(
        date(2021, 12, 1),
        email_job,
        notification_status=NOTIFICATION_DELIVERED,
        count=29,
    )

    sample_ft_notification_status(
        date(2022, 1, 1),
        sample_job(sms_template),
        notification_status=NOTIFICATION_DELIVERED,
        count=14,
    )

    response = get_monthly_platform_stats()

    assert response.status_code == 200

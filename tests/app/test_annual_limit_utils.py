import pytest

from app.annual_limit_utils import get_annual_limit_notifications_v2
from tests.conftest import set_config


class TestAnnualLimitUtils:
    @pytest.mark.parametrize(
        "redis_value, db_value_year, db_value_day", [(None, 5, [(None, "email", "sent", 1), (None, "sms", "sent", 2)])]
    )
    def test_get_annual_limit_notifications_v2(self, client, mocker, sample_service, redis_value, db_value_year, db_value_day):
        mocker.patch("app.annual_limit_client.was_seeded_today", return_value=False)
        mocker.patch("app.annual_limit_client.set_seeded_at")
        mocker.patch(
            "app.annual_limit_utils.fetch_notification_status_totals_for_service_by_fiscal_year", return_value=db_value_year
        )
        mocker.patch("app.annual_limit_utils.fetch_notification_status_for_service_for_day", return_value=db_value_day)

        with set_config(client.application, "REDIS_ENABLED", True):
            result = get_annual_limit_notifications_v2(sample_service.id)

        assert result == {
            "email_delivered_today": 1,
            "email_failed_today": 0,
            "sms_failed_today": 0,
            "sms_delivered_today": 2,
            "total_sms_fiscal_year_to_yesterday": 5,
            "total_email_fiscal_year_to_yesterday": 5,
        }

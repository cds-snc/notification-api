import pytest

from app.annual_limit_utils import (
    get_annual_limit_notifications_v2,
    increment_notifications_delivered,
    increment_notifications_failed,
)
from app.models import EMAIL_TYPE, SMS_TYPE
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

    @pytest.mark.parametrize(
        "notification_type, function_called",
        [
            (EMAIL_TYPE, "increment_email_failed"),
            (SMS_TYPE, "increment_sms_failed"),
        ],
    )
    def test_increment_notifications_failed_when_seeded(self, client, mocker, sample_service, notification_type, function_called):
        mock_was_seeded = mocker.patch("app.annual_limit_client.was_seeded_today", return_value=True)
        mock_increment_email_failed = mocker.patch("app.annual_limit_client.increment_email_failed")
        mock_increment_sms_failed = mocker.patch("app.annual_limit_client.increment_sms_failed")
        mock_seed = mocker.patch("app.annual_limit_utils.seed_annual_limit_counts")
        with set_config(client.application, "REDIS_ENABLED", True):
            increment_notifications_failed(sample_service.id, notification_type)
        mock_was_seeded.assert_called_once_with(sample_service.id)
        mock_seed.assert_not_called()
        if notification_type == EMAIL_TYPE:
            mock_increment_email_failed.assert_called_once_with(sample_service.id)
            mock_increment_sms_failed.assert_not_called()
        else:
            mock_increment_sms_failed.assert_called_once_with(sample_service.id)
            mock_increment_email_failed.assert_not_called()

    def test_increment_notifications_failed_not_called_when_not_seeded(self, client, mocker, sample_service):
        mock_was_seeded = mocker.patch("app.annual_limit_client.was_seeded_today", return_value=False)
        mock_increment_email_failed = mocker.patch("app.annual_limit_client.increment_email_failed")
        mock_increment_sms_failed = mocker.patch("app.annual_limit_client.increment_sms_failed")
        mock_seed = mocker.patch("app.annual_limit_utils.seed_annual_limit_counts")
        with set_config(client.application, "REDIS_ENABLED", True):
            increment_notifications_failed(sample_service.id, EMAIL_TYPE)
        mock_was_seeded.assert_called_once_with(sample_service.id)
        mock_seed.assert_called_once_with(sample_service.id)
        mock_increment_email_failed.assert_not_called()
        mock_increment_sms_failed.assert_not_called()

    @pytest.mark.parametrize(
        "notification_type, function_called",
        [
            (EMAIL_TYPE, "increment_email_delivered"),
            (SMS_TYPE, "increment_sms_delivered"),
        ],
    )
    def test_increment_notifications_delivered_when_seeded(
        self, client, mocker, sample_service, notification_type, function_called
    ):
        mock_was_seeded = mocker.patch("app.annual_limit_client.was_seeded_today", return_value=True)
        mock_increment_email_delivered = mocker.patch("app.annual_limit_client.increment_email_delivered")
        mock_increment_sms_delivered = mocker.patch("app.annual_limit_client.increment_sms_delivered")
        mock_seed = mocker.patch("app.annual_limit_utils.seed_annual_limit_counts")
        with set_config(client.application, "REDIS_ENABLED", True):
            increment_notifications_delivered(sample_service.id, notification_type)
        mock_was_seeded.assert_called_once_with(sample_service.id)
        mock_seed.assert_not_called()
        if notification_type == EMAIL_TYPE:
            mock_increment_email_delivered.assert_called_once_with(sample_service.id)
            mock_increment_sms_delivered.assert_not_called()
        else:
            mock_increment_sms_delivered.assert_called_once_with(sample_service.id)
            mock_increment_email_delivered.assert_not_called()

    def test_increment_notifications_delivered_not_called_when_not_seeded(self, client, mocker, sample_service):
        mock_was_seeded = mocker.patch("app.annual_limit_client.was_seeded_today", return_value=False)
        mock_increment_email_delivered = mocker.patch("app.annual_limit_client.increment_email_delivered")
        mock_increment_sms_delivered = mocker.patch("app.annual_limit_client.increment_sms_delivered")
        mock_seed = mocker.patch("app.annual_limit_utils.seed_annual_limit_counts")
        with set_config(client.application, "REDIS_ENABLED", True):
            increment_notifications_delivered(sample_service.id, SMS_TYPE)
        mock_was_seeded.assert_called_once_with(sample_service.id)
        mock_seed.assert_called_once_with(sample_service.id)
        mock_increment_email_delivered.assert_not_called()
        mock_increment_sms_delivered.assert_not_called()

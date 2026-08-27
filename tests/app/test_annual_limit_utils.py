import pytest

from app.annual_limit_utils import get_annual_limit_notifications_v2, seed_data_in_redis
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
        # Mock billable units functions for when FF_USE_BILLABLE_UNITS is enabled
        mocker.patch("app.annual_limit_utils.fetch_billable_units_totals_for_service_by_fiscal_year", return_value=0)
        mocker.patch("app.annual_limit_utils.fetch_billable_units_for_service_for_day", return_value=[])

        with set_config(client.application, "REDIS_ENABLED", True):
            result = get_annual_limit_notifications_v2(sample_service.id)

        expected = {
            "email_delivered_today": 1,
            "email_failed_today": 0,
            "sms_failed_today": 0,
            "sms_delivered_today": 2,
            "total_sms_fiscal_year_to_yesterday": 5,
            "total_email_fiscal_year_to_yesterday": 5,
        }

        # When FF_USE_BILLABLE_UNITS is enabled, additional fields are included
        if client.application.config.get("FF_USE_BILLABLE_UNITS"):
            expected.update(
                {
                    "total_sms_billable_units_fiscal_year_to_yesterday": 0,
                    "sms_billable_units_failed_today": 0,
                    "sms_billable_units_delivered_today": 0,
                }
            )

        assert result == expected

    def test_seed_data_in_redis_sets_seeded_at_when_all_counts_are_zero(self, client, mocker, sample_service):
        """When all notification counts are zero, seed_annual_limit_notifications short-circuits
        and never calls set_seeded_at(). seed_data_in_redis must catch this and call set_seeded_at()
        itself to prevent an infinite re-seeding loop on every API request.
        """
        mocker.patch("app.annual_limit_utils.fetch_notification_status_totals_for_service_by_fiscal_year", return_value=0)
        mocker.patch("app.annual_limit_utils.fetch_notification_status_for_service_for_day", return_value=[])
        mocker.patch("app.annual_limit_utils.fetch_billable_units_totals_for_service_by_fiscal_year", return_value=0)
        mocker.patch("app.annual_limit_utils.fetch_billable_units_for_service_for_day", return_value=[])

        mock_seed = mocker.patch("app.annual_limit_client.seed_annual_limit_notifications")
        mock_set_seeded_at = mocker.patch("app.annual_limit_client.set_seeded_at")

        with set_config(client.application, "REDIS_ENABLED", True):
            result = seed_data_in_redis(sample_service.id)

        # All counts should be zero
        assert all(v == 0 for v in result.values())

        # seed_annual_limit_notifications was called (it will short-circuit internally)
        mock_seed.assert_called_once()

        # set_seeded_at must be called to prevent the re-seeding loop
        mock_set_seeded_at.assert_called_once_with(sample_service.id)

    def test_seed_data_in_redis_does_not_double_set_seeded_at_when_counts_nonzero(self, client, mocker, sample_service):
        """When notification counts are non-zero, seed_annual_limit_notifications handles
        set_seeded_at() itself — seed_data_in_redis should NOT call it again.
        """
        mocker.patch("app.annual_limit_utils.fetch_notification_status_totals_for_service_by_fiscal_year", return_value=5)
        mocker.patch(
            "app.annual_limit_utils.fetch_notification_status_for_service_for_day",
            return_value=[(None, "email", "sent", 1), (None, "sms", "sent", 2)],
        )
        mocker.patch("app.annual_limit_utils.fetch_billable_units_totals_for_service_by_fiscal_year", return_value=0)
        mocker.patch("app.annual_limit_utils.fetch_billable_units_for_service_for_day", return_value=[])

        mock_seed = mocker.patch("app.annual_limit_client.seed_annual_limit_notifications")
        mock_set_seeded_at = mocker.patch("app.annual_limit_client.set_seeded_at")

        with set_config(client.application, "REDIS_ENABLED", True):
            result = seed_data_in_redis(sample_service.id)

        # Some counts are non-zero
        assert not all(v == 0 for v in result.values())

        # seed_annual_limit_notifications was called
        mock_seed.assert_called_once()

        # set_seeded_at should NOT be called by seed_data_in_redis (it's handled inside seed_annual_limit_notifications)
        mock_set_seeded_at.assert_not_called()

from datetime import datetime

import pytest
from freezegun import freeze_time

from app.job.daily_limits import release_daily_limit_for_cancelled_job
from tests.app.db import create_api_key, create_job, create_template
from tests.conftest import set_config

REAL_SMS_CSV = "phone number\n6502532222\n6502532223\n"
SIMULATED_SMS_CSV = "phone number\n+16132532222\n+16132532223\n"
LONG_SMS_TEMPLATE_CONTENT = "a" * 200  # 2 fragments per message


@pytest.fixture
def decrement_mocks(mocker):
    return {
        "email": mocker.patch("app.job.daily_limits.decrement_todays_email_count"),
        "sms": mocker.patch("app.job.daily_limits.decrement_todays_requested_sms_count"),
        "sms_billable_units": mocker.patch("app.job.daily_limits.decrement_todays_requested_sms_billable_units_count"),
    }


@freeze_time("2026-11-12 15:00:00")
class TestReleaseDailyLimitForCancelledJob:
    def test_email_job_scheduled_for_today_decrements_email_count(self, sample_email_template, decrement_mocks):
        job = create_job(
            sample_email_template, notification_count=5, job_status="scheduled", scheduled_for=datetime(2026, 11, 12, 20)
        )

        release_daily_limit_for_cancelled_job(job)

        decrement_mocks["email"].assert_called_once_with(job.service_id, 5)
        decrement_mocks["sms"].assert_not_called()
        decrement_mocks["sms_billable_units"].assert_not_called()

    def test_email_job_scheduled_for_future_day_does_not_decrement(self, sample_email_template, decrement_mocks):
        job = create_job(
            sample_email_template, notification_count=5, job_status="scheduled", scheduled_for=datetime(2026, 11, 13, 10)
        )

        release_daily_limit_for_cancelled_job(job)

        decrement_mocks["email"].assert_not_called()

    def test_email_job_created_on_previous_day_does_not_decrement(self, sample_email_template, decrement_mocks):
        job = create_job(
            sample_email_template,
            notification_count=5,
            job_status="scheduled",
            created_at=datetime(2026, 11, 11, 15),
            scheduled_for=datetime(2026, 11, 12, 20),
        )

        release_daily_limit_for_cancelled_job(job)

        decrement_mocks["email"].assert_not_called()

    @pytest.mark.parametrize("scheduled_for", [datetime(2026, 11, 12, 20), datetime(2026, 11, 14, 10)])
    def test_sms_job_decrements_sms_count_by_rows(self, notify_api, sample_template, decrement_mocks, mocker, scheduled_for):
        mocker.patch("app.job.daily_limits.get_job_from_s3", return_value=REAL_SMS_CSV)
        job = create_job(sample_template, notification_count=2, job_status="scheduled", scheduled_for=scheduled_for)

        with set_config(notify_api, "FF_USE_BILLABLE_UNITS", False):
            release_daily_limit_for_cancelled_job(job)

        decrement_mocks["sms"].assert_called_once_with(job.service_id, 2)
        decrement_mocks["sms_billable_units"].assert_not_called()
        decrement_mocks["email"].assert_not_called()

    def test_sms_job_decrements_billable_units_when_ff_on(self, notify_api, sample_template, decrement_mocks, mocker):
        long_template = create_template(sample_template.service, template_name="long sms", content=LONG_SMS_TEMPLATE_CONTENT)
        mocker.patch("app.job.daily_limits.get_job_from_s3", return_value=REAL_SMS_CSV)
        job = create_job(long_template, notification_count=2, job_status="scheduled", scheduled_for=datetime(2026, 11, 12, 20))

        with set_config(notify_api, "FF_USE_BILLABLE_UNITS", True):
            release_daily_limit_for_cancelled_job(job)

        decrement_mocks["sms_billable_units"].assert_called_once_with(job.service_id, 4)
        decrement_mocks["sms"].assert_not_called()

    def test_sms_job_with_simulated_recipients_does_not_decrement(self, sample_template, decrement_mocks, mocker):
        mocker.patch("app.job.daily_limits.get_job_from_s3", return_value=SIMULATED_SMS_CSV)
        job = create_job(sample_template, notification_count=2, job_status="scheduled", scheduled_for=datetime(2026, 11, 12, 20))

        release_daily_limit_for_cancelled_job(job)

        decrement_mocks["sms"].assert_not_called()
        decrement_mocks["sms_billable_units"].assert_not_called()

    def test_sms_job_created_with_test_api_key_does_not_decrement(self, sample_template, decrement_mocks, mocker):
        mock_s3 = mocker.patch("app.job.daily_limits.get_job_from_s3", return_value=REAL_SMS_CSV)
        job = create_job(sample_template, notification_count=2, job_status="scheduled", scheduled_for=datetime(2026, 11, 12, 20))
        job.api_key = create_api_key(sample_template.service, key_type="test")

        release_daily_limit_for_cancelled_job(job)

        mock_s3.assert_not_called()
        decrement_mocks["sms"].assert_not_called()
        decrement_mocks["sms_billable_units"].assert_not_called()

    def test_sms_job_created_on_previous_day_does_not_decrement(self, sample_template, decrement_mocks, mocker):
        mock_s3 = mocker.patch("app.job.daily_limits.get_job_from_s3", return_value=REAL_SMS_CSV)
        job = create_job(
            sample_template,
            notification_count=2,
            job_status="scheduled",
            created_at=datetime(2026, 11, 11, 15),
            scheduled_for=datetime(2026, 11, 12, 20),
        )

        release_daily_limit_for_cancelled_job(job)

        mock_s3.assert_not_called()
        decrement_mocks["sms"].assert_not_called()

    def test_sms_job_s3_failure_is_logged_and_does_not_raise(self, sample_template, decrement_mocks, mocker):
        mocker.patch("app.job.daily_limits.get_job_from_s3", side_effect=Exception("S3 is down"))
        mock_logger = mocker.patch("app.job.daily_limits.current_app.logger.exception")
        job = create_job(sample_template, notification_count=2, job_status="scheduled", scheduled_for=datetime(2026, 11, 12, 20))

        release_daily_limit_for_cancelled_job(job)

        mock_logger.assert_called_once()
        decrement_mocks["sms"].assert_not_called()

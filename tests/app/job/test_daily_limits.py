from datetime import datetime

import pytest
from freezegun import freeze_time

from app.job.daily_limits import release_daily_limit_for_cancelled_job
from tests.app.db import create_api_key, create_job
from tests.conftest import set_config

TODAY = datetime(2026, 11, 12, 20)
LATER_DAY = datetime(2026, 11, 14, 10)


@pytest.fixture
def decrement_mocks(mocker):
    return {
        "email": mocker.patch("app.job.daily_limits.decrement_todays_email_count"),
        "sms": mocker.patch("app.job.daily_limits.decrement_todays_requested_sms_count"),
        "sms_billable_units": mocker.patch("app.job.daily_limits.decrement_todays_requested_sms_billable_units_count"),
    }


def _assert_nothing_decremented(decrement_mocks):
    for mock in decrement_mocks.values():
        mock.assert_not_called()


@freeze_time("2026-11-12 15:00:00")
class TestReleaseDailyLimitForCancelledJob:
    @pytest.mark.parametrize("created_at", [datetime(2026, 11, 12, 14), datetime(2026, 11, 10, 14)])
    def test_email_job_scheduled_for_today_decrements_email_count(self, sample_email_template, decrement_mocks, created_at):
        # A job created on an earlier day is in today's count once today's count is loaded from the database
        job = create_job(
            sample_email_template, notification_count=5, job_status="scheduled", scheduled_for=TODAY, created_at=created_at
        )

        release_daily_limit_for_cancelled_job(job)

        decrement_mocks["email"].assert_called_once_with(job.service_id, 5)
        decrement_mocks["sms"].assert_not_called()
        decrement_mocks["sms_billable_units"].assert_not_called()

    def test_email_job_scheduled_for_later_day_does_not_decrement(self, sample_email_template, decrement_mocks):
        job = create_job(sample_email_template, notification_count=5, job_status="scheduled", scheduled_for=LATER_DAY)

        release_daily_limit_for_cancelled_job(job)

        _assert_nothing_decremented(decrement_mocks)

    def test_email_job_created_with_test_api_key_does_not_decrement(self, sample_email_template, decrement_mocks):
        api_key = create_api_key(sample_email_template.service, key_type="test")
        job = create_job(
            sample_email_template, notification_count=5, job_status="scheduled", scheduled_for=TODAY, api_key=api_key
        )

        release_daily_limit_for_cancelled_job(job)

        _assert_nothing_decremented(decrement_mocks)

    @pytest.mark.parametrize("created_at", [datetime(2026, 11, 12, 14), datetime(2026, 11, 10, 14)])
    def test_sms_job_scheduled_for_today_decrements_sms_count(self, notify_api, sample_template, decrement_mocks, created_at):
        job = create_job(
            sample_template,
            notification_count=2,
            billable_units=4,
            job_status="scheduled",
            scheduled_for=TODAY,
            created_at=created_at,
        )

        with set_config(notify_api, "FF_USE_BILLABLE_UNITS", False):
            release_daily_limit_for_cancelled_job(job)

        decrement_mocks["sms"].assert_called_once_with(job.service_id, 2)
        decrement_mocks["sms_billable_units"].assert_not_called()
        decrement_mocks["email"].assert_not_called()

    def test_sms_job_scheduled_for_today_decrements_billable_units_when_ff_on(self, notify_api, sample_template, decrement_mocks):
        job = create_job(sample_template, notification_count=2, billable_units=4, job_status="scheduled", scheduled_for=TODAY)

        with set_config(notify_api, "FF_USE_BILLABLE_UNITS", True):
            release_daily_limit_for_cancelled_job(job)

        decrement_mocks["sms_billable_units"].assert_called_once_with(job.service_id, 4)
        decrement_mocks["sms"].assert_not_called()

    @pytest.mark.parametrize("ff_use_billable_units", [True, False])
    def test_sms_job_scheduled_for_later_day_does_not_decrement(
        self, notify_api, sample_template, decrement_mocks, ff_use_billable_units
    ):
        job = create_job(sample_template, notification_count=2, billable_units=4, job_status="scheduled", scheduled_for=LATER_DAY)

        with set_config(notify_api, "FF_USE_BILLABLE_UNITS", ff_use_billable_units):
            release_daily_limit_for_cancelled_job(job)

        _assert_nothing_decremented(decrement_mocks)

    @pytest.mark.parametrize("billable_units", [0, None], ids=["not counted", "created before billable_units"])
    def test_sms_job_not_counted_does_not_decrement(self, sample_template, decrement_mocks, billable_units):
        job = create_job(
            sample_template, notification_count=2, billable_units=billable_units, job_status="scheduled", scheduled_for=TODAY
        )

        release_daily_limit_for_cancelled_job(job)

        _assert_nothing_decremented(decrement_mocks)

    def test_sms_job_created_with_test_api_key_does_not_decrement(self, sample_template, decrement_mocks):
        api_key = create_api_key(sample_template.service, key_type="test")
        job = create_job(
            sample_template, notification_count=2, billable_units=2, job_status="scheduled", scheduled_for=TODAY, api_key=api_key
        )

        release_daily_limit_for_cancelled_job(job)

        _assert_nothing_decremented(decrement_mocks)

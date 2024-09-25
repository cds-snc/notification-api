import pytest

from tests.conftest import set_config
from app.googleanalytics.pixels import build_dynamic_ga4_pixel_tracking_url


class TestGA4PixelTracking:
    @pytest.mark.parametrize(
        'domain',
        [
            'https://test-api.va.gov/vanotify/',
            'https://dev-api.va.gov/vanotify/',
            'https://sandbox-api.va.gov/vanotify/',
            'https://staging-api.va.gov/vanotify/',
            'https://api.va.gov/vanotify/',
        ],
    )
    def test_ut_build_dynamic_ga4_pixel_tracking_url_correct_domain_for_environment(
        self, notify_api, sample_notification_model_with_organization, domain
    ):
        with set_config(notify_api, 'PUBLIC_DOMAIN', domain):
            url = build_dynamic_ga4_pixel_tracking_url(sample_notification_model_with_organization)
            assert domain in url

    def test_ut_build_dynamic_ga4_pixel_tracking_url_correct_path(self, sample_notification):
        notification = sample_notification()
        url = build_dynamic_ga4_pixel_tracking_url(notification)
        assert f'ga4/open-email-tracking/{notification.id}' in url

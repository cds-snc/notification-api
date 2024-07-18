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

    def test_ut_build_dynamic_ga4_pixel_tracking_url_contains_expected_parameters(
        self, sample_notification_model_with_organization
    ):
        url = build_dynamic_ga4_pixel_tracking_url(sample_notification_model_with_organization)

        all_expected_parameters = [
            'campaign=',
            'campaign_id=',
            'name=email_open',
            'source=vanotify',
            'medium=email',
            'content=',
        ]

        assert all(parameter in url for parameter in all_expected_parameters)

    def test_ut_build_dynamic_ga4_pixel_tracking_url_encodes_spaces(self, sample_notification_model_with_organization):
        sample_notification_model_with_organization.template.name = 'Test Campaign'
        sample_notification_model_with_organization.service.name = 'Test Service'

        url = build_dynamic_ga4_pixel_tracking_url(sample_notification_model_with_organization)

        assert 'Test%20Campaign' in url
        assert 'Test%20Service' in url

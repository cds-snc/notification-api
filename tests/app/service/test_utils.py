import pytest

from app.service.utils import compute_source_email_address, compute_source_email_address_with_display_name
from tests.conftest import set_config_values

DEFAULT_EMAIL_FROM_VALUES = {
    'NOTIFY_EMAIL_FROM_DOMAIN': 'default.domain',
    'NOTIFY_EMAIL_FROM_USER': 'default-email-from',
    'NOTIFY_EMAIL_FROM_NAME': 'Default Name',
}


@pytest.mark.parametrize(
    'service_sending_domain, service_email_from, expected_source_email_address',
    [
        (None, None, 'default-email-from@default.domain'),
        ('custom.domain', None, 'default-email-from@custom.domain'),
        (None, 'custom-email-from', 'custom-email-from@default.domain')
    ]
)
def test_should_compute_source_email_address(
        sample_service,
        notify_api,
        service_sending_domain,
        service_email_from,
        expected_source_email_address
):
    sample_service.sending_domain = service_sending_domain
    sample_service.email_from = service_email_from

    with set_config_values(notify_api, DEFAULT_EMAIL_FROM_VALUES):
        assert compute_source_email_address(sample_service) == expected_source_email_address


def test_should_compute_source_email_address_with_display_name(
        sample_service,
        notify_api,
        mocker
):
    mocker.patch('app.service.utils.compute_source_email_address', return_value='some@email.com')

    with set_config_values(notify_api, DEFAULT_EMAIL_FROM_VALUES):
        assert compute_source_email_address_with_display_name(sample_service) == '"Default Name" <some@email.com>'

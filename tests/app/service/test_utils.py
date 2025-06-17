import pytest
from datetime import datetime, timezone
from freezegun import freeze_time

from app.clients.email import EmailClient
from app.errors import InvalidRequest
from app.service.utils import compute_source_email_address, validate_expiry_date
from tests.conftest import set_config_values

DEFAULT_EMAIL_FROM_VALUES = {
    'NOTIFY_EMAIL_FROM_DOMAIN': 'default.domain',
    'NOTIFY_EMAIL_FROM_USER': 'default-email-from',
    'NOTIFY_EMAIL_FROM_NAME': 'Default Name',
}


@pytest.mark.parametrize(
    'service_sending_domain, service_email_from, provider_from_domain, provider_from_user,'
    'expected_source_email_address',
    [
        (None, None, None, None, 'default-email-from@default.domain'),
        ('custom.domain', None, None, None, 'default-email-from@custom.domain'),
        (None, 'custom-email-from', None, None, 'custom-email-from@default.domain'),
        (None, None, 'provider.domain', 'provider-from-user', 'provider-from-user@provider.domain'),
        (
            'custom.domain',
            'custom-email-from',
            'provider.domain',
            'provider-from-user',
            'custom-email-from@custom.domain',
        ),
    ],
)
def test_should_compute_source_email_address(
    sample_service,
    notify_api,
    mocker,
    service_sending_domain,
    service_email_from,
    provider_from_domain,
    provider_from_user,
    expected_source_email_address,
):
    sample_service.sending_domain = service_sending_domain
    sample_service.email_from = service_email_from
    mock_email_client = mocker.Mock(spec=EmailClient)
    mocker.patch.object(
        mock_email_client, 'email_from_domain', new_callable=mocker.PropertyMock(return_value=provider_from_domain)
    )
    mocker.patch.object(
        mock_email_client, 'email_from_user', new_callable=mocker.PropertyMock(return_value=provider_from_user)
    )
    with set_config_values(notify_api, DEFAULT_EMAIL_FROM_VALUES):
        assert (
            compute_source_email_address(sample_service, mock_email_client)
            == f'"Default Name" <{expected_source_email_address}>'
        )


@freeze_time('2025-01-01T11:00:00+00:00')
class TestValidateExpiryDate:
    def test_validate_expiry_date_happy_path(self) -> None:
        """Test that validate_expiry_date returns a datetime object for a valid future date."""
        assert validate_expiry_date('2025-10-01') == datetime(2025, 10, 1, 0, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize(
        'expiry_date',
        [
            '2023-10-01',
            'invalid-date',
            None,
        ],
        ids=[
            'past-date',
            'invalid-format',
            'none',
        ],
    )
    def test_validates_expiry_date_invalid(self, expiry_date) -> None:
        with pytest.raises(InvalidRequest):
            validate_expiry_date(expiry_date)

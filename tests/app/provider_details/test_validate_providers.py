import pytest

from app.constants import EMAIL_TYPE, SMS_TYPE
from app.models import ProviderDetails
from app.provider_details.validate_providers import is_provider_valid

PROVIDER_DETAILS_BY_ID_PATH = 'app.provider_details.validate_providers.get_provider_details_by_id'


def test_check_provider_exists(notify_db, fake_uuid):
    assert is_provider_valid(fake_uuid, EMAIL_TYPE) is False


@pytest.mark.parametrize(
    'is_active, notification_type, checked_notification_type, expected_result',
    [(True, SMS_TYPE, EMAIL_TYPE, False), (False, EMAIL_TYPE, EMAIL_TYPE, False), (True, EMAIL_TYPE, EMAIL_TYPE, True)],
)
def test_check_provider_is_active(
    notify_api,
    mocker,
    fake_uuid,
    is_active,
    notification_type,
    checked_notification_type,
    expected_result,
):
    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = is_active
    mocked_provider_details.notification_type = notification_type
    mocker.patch(PROVIDER_DETAILS_BY_ID_PATH, return_value=mocked_provider_details)
    assert is_provider_valid(fake_uuid, checked_notification_type) is expected_result

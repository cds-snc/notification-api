from app.models import ProviderDetails, EMAIL_TYPE, SMS_TYPE
from app.provider_details.validate_providers import is_provider_valid

PROVIDER_DETAILS_BY_ID_PATH = 'app.provider_details.validate_providers.get_provider_details_by_id'


def test_check_provider_exists(notify_db, fake_uuid):
    assert is_provider_valid(fake_uuid, 'email') is False


def test_check_provider_is_active_and_of_incorrect_type(mocker, fake_uuid):
    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = True
    mocked_provider_details.notification_type = SMS_TYPE
    mocker.patch(
        PROVIDER_DETAILS_BY_ID_PATH,
        return_value=mocked_provider_details
    )
    assert is_provider_valid(fake_uuid, EMAIL_TYPE) is False


def test_check_provider_is_inactive_and_of_correct_type(mocker, fake_uuid):
    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = False
    mocked_provider_details.notification_type = EMAIL_TYPE
    mocker.patch(
        PROVIDER_DETAILS_BY_ID_PATH,
        return_value=mocked_provider_details
    )
    assert is_provider_valid(fake_uuid, EMAIL_TYPE) is False


def test_check_provider_is_active_and_of_correct_type(mocker, fake_uuid):
    mocked_provider_details = mocker.Mock(ProviderDetails)
    mocked_provider_details.active = True
    mocked_provider_details.notification_type = EMAIL_TYPE
    mocker.patch(
        PROVIDER_DETAILS_BY_ID_PATH,
        return_value=mocked_provider_details
    )
    assert is_provider_valid(fake_uuid, EMAIL_TYPE) is True

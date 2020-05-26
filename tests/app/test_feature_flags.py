from app.feature_flags import is_provider_enabled


def test_is_govdelivery_enabled(mocker):
    current_app = mocker.Mock(config={
        'GOVDELIVERY_EMAIL_CLIENT_ENABLED': True
    })
    assert is_provider_enabled(current_app, 'govdelivery')


def test_is_provider_without_a_flag_enabled(mocker):
    current_app = mocker.Mock(config={})
    assert is_provider_enabled(current_app, 'some-provider-without-a-flag')

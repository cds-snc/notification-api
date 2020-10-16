from app.feature_flags import is_provider_enabled, accept_recipient_identifiers_enabled


def test_is_govdelivery_enabled(mocker):
    current_app = mocker.Mock(config={
        'GOVDELIVERY_EMAIL_CLIENT_ENABLED': True
    })
    assert is_provider_enabled(current_app, 'govdelivery')


def test_is_provider_without_a_flag_enabled(mocker):
    current_app = mocker.Mock(config={})
    assert is_provider_enabled(current_app, 'some-provider-without-a-flag')


def test_accept_recipient_identifiers_enabled(mocker):
    current_app = mocker.Mock(config={
        'ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED': True
    })
    assert accept_recipient_identifiers_enabled(current_app)


def test_accept_recipient_identifiers_not_enabled(mocker):
    current_app = mocker.Mock(config={
        'ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED': False
    })
    assert not accept_recipient_identifiers_enabled(current_app)

import os

import pytest

from app.feature_flags import is_provider_enabled, accept_recipient_identifiers_enabled, is_gapixel_enabled


def test_is_govdelivery_enabled(mocker):
    current_app = mocker.Mock(config={
        'GOVDELIVERY_EMAIL_CLIENT_ENABLED': True
    })
    assert is_provider_enabled(current_app, 'govdelivery')


def test_is_provider_without_a_flag_enabled(mocker):
    current_app = mocker.Mock(config={})
    assert is_provider_enabled(current_app, 'some-provider-without-a-flag')


@pytest.mark.parametrize('enabled_string, enabled_boolean', [
    ('True', True),
    ('False', False)
])
def test_accept_recipient_identifiers_flag(mocker, enabled_string, enabled_boolean):
    mocker.patch.dict(os.environ, {'ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED': enabled_string})
    assert accept_recipient_identifiers_enabled() == enabled_boolean


@pytest.mark.parametrize('gapixel_enabled', [
    'True',
    'False'
])
def test_accept_gapixel_enabled_flag(mocker, gapixel_enabled):
    current_app = mocker.Mock(config={
        'GOOGLE_ANALYTICS_ENABLED': gapixel_enabled
    })
    assert str(is_gapixel_enabled(current_app)) == gapixel_enabled

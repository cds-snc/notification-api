import os

import pytest

from app.feature_flags import (
    FeatureFlag,
    is_feature_enabled,
    accept_recipient_identifiers_enabled,
    is_gapixel_enabled,
)


@pytest.mark.parametrize('enabled_string, enabled_boolean', [('True', True), ('False', False)])
def test_accept_recipient_identifiers_flag(mocker, enabled_string, enabled_boolean):
    mocker.patch.dict(os.environ, {'ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED': enabled_string})
    assert accept_recipient_identifiers_enabled() == enabled_boolean


@pytest.mark.parametrize('gapixel_enabled', ['True', 'False'])
def test_accept_gapixel_enabled_flag(mocker, gapixel_enabled):
    current_app = mocker.Mock(config={'GOOGLE_ANALYTICS_ENABLED': gapixel_enabled})
    assert str(is_gapixel_enabled(current_app)) == gapixel_enabled


@pytest.mark.parametrize(
    'feature_env_value, feature_enabled', [('True', True), ('False', False), (None, False), ('FooBar', False)]
)
def test_is_feature_enabled(mocker, feature_env_value, feature_enabled):
    mock_feature_flag = mocker.Mock(FeatureFlag)
    mock_feature_flag.value = 'IS_MOCK_FEATURE_ENABLED'
    mocker.patch('app.feature_flags.os.getenv', return_value=feature_env_value)
    assert is_feature_enabled(mock_feature_flag) == feature_enabled


def test_is_nonsense_feature_enabled():
    assert not is_feature_enabled('not an enum')

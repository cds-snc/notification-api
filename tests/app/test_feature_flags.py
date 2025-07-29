import pytest

from app.feature_flags import (
    FeatureFlag,
    is_feature_enabled,
)


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

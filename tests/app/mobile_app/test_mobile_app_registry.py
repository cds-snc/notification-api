import os
import pytest
from unittest.mock import Mock

from app.mobile_app.mobile_app_registry import MobileAppRegistry
from app.mobile_app.mobile_app_types import MobileAppType


@pytest.fixture(autouse=True)
def mock_logger():
    logger = Mock()
    return logger


@pytest.mark.parametrize(
    'apps, sids',
    [
        ([MobileAppType.VETEXT, MobileAppType.VA_FLAGSHIP_APP], ['sid1', 'sid2']),
        ([MobileAppType.VETEXT], ['vetext_sid']),
        ([MobileAppType.VA_FLAGSHIP_APP], ['flagsip_sid']),
    ],
)
def test_registry_initilizes_mobile_apps(
    client,
    mocker,
    apps,
    sids,
    mock_logger,
):
    for app, sid in zip(apps, sids):
        mocker.patch.dict(os.environ, {f'{app.value}_SID': sid})

    registry = MobileAppRegistry(mock_logger)

    for app, sid in zip(apps, sids):
        assert registry.get_app(app).sid == sid
        assert app in registry.get_registered_apps()


@pytest.mark.parametrize(
    'env, registered_app',
    [
        ({'VETEXT_SID': 'sid1', 'VA_FLAGSHIP_APP_SID': ''}, MobileAppType.VETEXT),
        ({'VETEXT_SID': '', 'VA_FLAGSHIP_APP_SID': 'some_sid'}, MobileAppType.VA_FLAGSHIP_APP),
        ({'VETEXT_SID': '', 'VA_FLAGSHIP_APP_SID': ''}, None),
    ],
)
def test_registry_initilizes_only_apps_with_sids_in_env(
    client,
    mocker,
    env,
    registered_app,
    mock_logger,
):
    """
    Note that the case where both apps have SIDs is tested above, in test_registry_initilizes_mobile_apps.
    """

    mocker.patch.dict(os.environ, env)
    registry = MobileAppRegistry(mock_logger)

    expected_list = [registered_app] if (registered_app is not None) else []
    assert registry.get_registered_apps() == expected_list


def test_should_log_warning_for_uninitialized_apps_with_correct_count(
    client,
    mock_logger,
    mocker,
):
    for app in MobileAppType.values():
        mocker.patch.dict(os.environ, {f'{app}_SID': ''})
    MobileAppRegistry(mock_logger)
    assert mock_logger.warning.call_count == len(MobileAppType.values())


@pytest.mark.parametrize('app_type_str', [*MobileAppType.values()])
def test_should_correctly_log_warning_for_uninitialized_apps(
    client,
    mock_logger,
    mocker,
    app_type_str,
):
    mocker.patch.dict(os.environ, {f'{app_type_str}_SID': ''})
    MobileAppRegistry(mock_logger)
    app_type = MobileAppType(app_type_str)
    mock_logger.warning.assert_called_once_with(
        'Missing environment sid for type: %s and value: %s_SID', app_type, app_type.value
    )

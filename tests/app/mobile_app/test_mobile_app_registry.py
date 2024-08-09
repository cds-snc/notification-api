import pytest
import os
from app.mobile_app import MobileAppType, MobileAppRegistry


@pytest.fixture(autouse=True)
def mock_logger(mocker):
    app_context_mock = mocker.patch('app.mobile_app.mobile_app_registry.current_app')
    return app_context_mock.logger


def test_registry_is_singleton(
    client,
):
    registry = MobileAppRegistry()
    another_registry = MobileAppRegistry()
    assert registry == another_registry


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
):
    for app, sid in zip(apps, sids):
        mocker.patch.dict(os.environ, {f'{app.value}_SID': sid})

    registry = MobileAppRegistry()

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
):
    mocker.patch.dict(os.environ, env)
    registry = MobileAppRegistry()

    expected_list = [registered_app] if registered_app else []
    assert registry.get_registered_apps() == expected_list


def test_should_log_error_for_uninitilized_apps(
    client,
    mock_logger,
    mocker,
):
    for app in MobileAppType.values():
        mocker.patch.dict(os.environ, {f'{app}_SID': ''})
    MobileAppRegistry()
    assert mock_logger.exception.call_count == len(MobileAppType.values())

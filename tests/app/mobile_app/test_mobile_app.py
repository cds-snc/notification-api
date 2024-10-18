import pytest
import os
from app.mobile_app import MobileApp, MobileAppType


@pytest.mark.parametrize(
    'app_type, app_sid',
    [
        (MobileAppType.VETEXT, '1234'),
        (MobileAppType.VA_FLAGSHIP_APP, 'qwerty'),
    ],
)
def test_mobile_app_init_reads_sid_from_env(mocker, app_type, app_sid):
    mocker.patch.dict(os.environ, {f'{app_type.value}_SID': app_sid})
    app = MobileApp(app_type)
    assert app.sid == app_sid


@pytest.mark.parametrize(
    'app_type, app_sid',
    [
        (MobileAppType.VETEXT, ''),
        (MobileAppType.VA_FLAGSHIP_APP, ''),
    ],
)
def test_mobile_app_raises_exception_at_invalid_sid(client, mocker, app_type: MobileAppType, app_sid: str):
    mocker.patch.dict(os.environ, {f'{app_type.value}_SID': app_sid})
    with pytest.raises(ValueError) as e:
        MobileApp(app_type)
    assert str(e.value) == f'Missing SID for app: {app_type.value}'

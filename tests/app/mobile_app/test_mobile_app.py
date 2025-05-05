import pytest
import os
from app.mobile_app import MobileApp, MobileAppType


def test_mobile_app_init_reads_sid_from_env(mocker):
    app_type = MobileAppType.VA_FLAGSHIP_APP
    app_sid = 'test_sid'

    mocker.patch.dict(os.environ, {f'{app_type.value}_SID': app_sid})

    app = MobileApp(app_type)
    assert app.sid == app_sid


def test_mobile_app_raises_exception_at_invalid_sid(client, mocker):
    app_type = MobileAppType.VA_FLAGSHIP_APP
    app_sid = ''

    mocker.patch.dict(os.environ, {f'{app_type}_SID': app_sid})

    with pytest.raises(ValueError) as e:
        MobileApp(app_type)
    assert str(e.value) == f'Missing SID for app: {app_type.value}'

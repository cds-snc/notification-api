import pytest
import os
from app.mobile_app.mobile_app import MobileApp
from app.mobile_app.mobile_app_types import MobileAppType


def test_mobile_app_init_reads_SID_from_env(mocker):
    mocker.patch.dict(os.environ, {f'{MobileAppType.VETEXT.value}_SID': '12345'})
    app = MobileApp(MobileAppType.VETEXT)
    assert app.sid == '12345'


def test_mobile_app_raises_exception(mocker):
    mocker.patch.dict(os.environ, {f'{MobileAppType.VETEXT.value}_SID': ''})
    with pytest.raises(ValueError) as e:
        MobileApp(MobileAppType.VETEXT)
    assert str(e.value) == f"Missing SID for app: {MobileAppType.VETEXT.value}"

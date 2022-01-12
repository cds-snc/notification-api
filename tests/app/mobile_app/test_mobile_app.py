import pytest
import os
from app.mobile_app.mobile_app import MobileApp
from app.mobile_app.mobile_app_types import MobileAppType


def test_mobile_app_init_reads_SID_from_env(mocker):
    mocker.patch.dict(os.environ, {f'{MobileAppType.VETEXT.value}_SID': '12345'})
    app = MobileApp(MobileAppType.VETEXT)
    assert app.sid == '12345'


@pytest.mark.parametrize(
    "app_name, app_sid, exception, ",
    [
        ('', '12345', ValueError('some error')),
        ('VA_FAKE_APP', '12345',  ValueError('some error')),
        (None, '12345', ValueError('some error')),
    ]
)

def test_mobile_app_raises_exception_at_invalid_app_name(mocker, app_name, app_sid, exception):
    mobile_app = MobileAppType.get_application_by_name(app_name)
    with pytest.raises(NameError) as e:
        MobileApp(mobile_app)
    assert str(e.value) == f"No such Mobile app with name: {app_name}"

@pytest.mark.parametrize(
    "app_name, app_sid",
    [
        ('VETEXT', ''),
        ('VETEXT', 'string_sid'),
        ('VETEXT', None),
    ]

)

def test_mobile_app_raises_exception_at_invalid_sid(mocker, app_name, app_sid):
    mobile_app = MobileAppType.get_application_by_name(app_name)
    mocker.patch.dict(os.environ, {f'{mobile_app}_SID': app_sid})
    with pytest.raises(ValueError) as e:
        MobileApp(MobileAppType.VETEXT)
    assert str(e.value) == f"Missing SID for app: {MobileAppType.VETEXT.value}"

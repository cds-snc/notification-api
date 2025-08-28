from enum import Enum


class MobileAppType(str, Enum):
    VA_FLAGSHIP_APP: str = 'VA_FLAGSHIP_APP'

    @staticmethod
    def values() -> list['MobileAppType']:
        return list(x.value for x in MobileAppType)


DEFAULT_MOBILE_APP_TYPE = MobileAppType.VA_FLAGSHIP_APP

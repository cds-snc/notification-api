import string
from enum import Enum
from typing import List
from .mobile_app_types import MobileAppType


class MobileAppType(Enum):
    VA_FLAGSHIP_APP = 'VA_FLAGSHIP_APP'
    VETEXT = 'VETEXT'

    @staticmethod
    def values() -> List['MobileAppType']:
        return list(x.value for x in MobileAppType)

    @staticmethod
    def get_application_by_name(app_name: string) -> MobileAppType:
        app = MobileAppType(app_name).name
        if not app:
            raise NameError(f"No such Mobile app with name: {app_name}")
        return app

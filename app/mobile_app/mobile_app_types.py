from enum import Enum
from typing import List


class MobileAppType(Enum):
    VA_FLAGSHIP_APP = 'VA_FLAGSHIP_APP'
    VETEXT = 'VETEXT'

    @staticmethod
    def values() -> List['MobileAppType']:
        return list(x.value for x in MobileAppType)

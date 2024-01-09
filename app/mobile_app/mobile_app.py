import os
from .mobile_app_types import MobileAppType


class MobileApp:
    def __init__(
        self,
        type: MobileAppType,
    ):
        self.type: MobileAppType = type
        self.sid = self._get_sid_from_env()

    def _get_sid_from_env(self):
        sid = os.getenv(f'{self.type.value}_SID', None)
        if not sid:
            raise ValueError(f'Missing SID for app: {self.type.value}')
        return sid

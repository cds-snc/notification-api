from typing import List

from .mobile_app import MobileApp
from .mobile_app_types import MobileAppType


class MobileAppRegistry:
    def __init__(self, logger):
        self.logger = logger
        self._registry = {}

        logger.info('Initializing MobileAppRegistry')
        for type in MobileAppType:
            try:
                app = MobileApp(type)
            except ValueError:
                logger.warning('Missing environment sid for type: %s and value: %s_SID', type, type.value)
            else:
                self._registry[type] = app

    def get_app(
        self,
        app_type: MobileAppType,
    ) -> MobileApp | None:
        return self._registry.get(app_type)

    def get_registered_apps(self) -> List[MobileAppType]:
        return list(self._registry.keys())

from .mobile_app_types import MobileAppType
from .mobile_app import MobileApp


class MobileAppRegistry():
    registry = {}

    def init(self):
        for type in MobileAppType:
            try:
                app = MobileApp(type)
            except Exception:
                pass
            else:
                self.registry[type] = app
